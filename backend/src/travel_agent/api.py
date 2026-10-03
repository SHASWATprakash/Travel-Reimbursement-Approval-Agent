"""FastAPI application; no API key, database or external cloud required."""
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .agent import AGENT_DEADLINE, MODEL
from .core import LIMIT_TABLE, TOOL_NAMES
from .demo_data import DEMO_CLAIMS, SCENARIO_LABELS
from .schemas import EvaluationJob, EvaluationRequest, EvaluationSnapshot
from .service import EvaluationService, QueueFullError


def create_app(service_factory=EvaluationService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service_factory()
        try:
            await app.state.service.start()
            yield
        finally:
            await app.state.service.close()

    app = FastAPI(title="Travel Reimbursement Companion", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = uuid4().hex
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.2f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/api/v1/health")
    async def health():
        available, installed = False, False
        try:
            async with httpx.AsyncClient(timeout=1.5, trust_env=False) as client:
                response = await client.get("http://127.0.0.1:11434/api/tags")
                response.raise_for_status()
                available = True
                installed = MODEL in {m.get("name") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError):
            pass
        return {"status": "ok", "version": "0.1.0", "model": MODEL,
                "live_available": available and installed, "ollama_available": available,
                "modes": ["rules", "replay", "live"], "deadline_seconds": AGENT_DEADLINE, "queue_capacity": 4,
                "queue_depth": app.state.service.queue.qsize()}

    @app.get("/api/v1/policies")
    async def policies():
        repo = app.state.service.repository
        return {"policy_version": repo.version, "rules": repo.rules, "limits": LIMIT_TABLE, "tools": list(TOOL_NAMES)}

    @app.get("/api/v1/sample-claims")
    async def claims():
        return {"claims": DEMO_CLAIMS, "scenario_labels": SCENARIO_LABELS}

    @app.get("/api/v1/evaluations/latest", response_model=EvaluationSnapshot)
    async def latest():
        return app.state.service.snapshot()

    @app.post("/api/v1/evaluations", status_code=202, response_model=EvaluationJob)
    async def evaluate(body: EvaluationRequest):
        try:
            return await app.state.service.submit(body)
        except KeyError as exc:
            raise HTTPException(404, "Unknown sample claim ID") from exc
        except QueueFullError as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": "5"}) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/v1/evaluations/{job_id}", response_model=EvaluationJob)
    async def job(job_id: str, include_results: bool = Query(default=True)):
        try:
            saved = app.state.service.get_job(job_id)
            if not include_results:
                saved.evaluations = []
            return saved
        except KeyError as exc:
            raise HTTPException(404, "Evaluation job not found or expired") from exc

    # Optional single-origin build: set TRAVEL_FRONTEND_DIST to the Vite dist directory.
    dist = Path(os.environ.get("TRAVEL_FRONTEND_DIST", "frontend/dist")).resolve()
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "API route not found")
            return FileResponse(dist / "index.html")

    logging.getLogger("mcp").setLevel(logging.WARNING)
    return app


app = create_app()
