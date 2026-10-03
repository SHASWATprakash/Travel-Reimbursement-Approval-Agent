"""Bounded local job queue; one model worker fits the available 8 GB machine."""
import asyncio
import copy
import json
from collections import OrderedDict
from datetime import datetime, timezone
from importlib.resources import files
from uuid import uuid4
from typing import Awaitable, Callable

from .agent import evaluate_claims
from .core import Claim, ClaimResult, Decision, PolicyRepository, TOOL_NAMES, fingerprint, jsonable, money
from .demo_data import DEMO_CLAIMS
from .schemas import EvaluationEnvelope, EvaluationJob, EvaluationRequest, EvaluationSnapshot
from .store import PostgresStore


def load_recordings() -> dict:
    recordings = json.loads(files("travel_agent").joinpath("data/recordings.json").read_text())
    companion = files("travel_agent").joinpath("data/companion-recordings.json")
    if companion.is_file():
        recordings.update(json.loads(companion.read_text()))
    return recordings


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class QueueFullError(RuntimeError):
    pass


class EvaluationService:
    def __init__(self, runner: Callable[..., Awaitable[list[dict]]] = evaluate_claims,
                 queue_limit: int = 4, history_limit: int = 32, store=None, claims=None):
        self.runner = runner
        self.recordings = load_recordings()
        self.repository = PolicyRepository()
        self.samples = {c["claim_id"]: copy.deepcopy(c) for c in (claims if claims is not None else DEMO_CLAIMS)}
        self.store = store if store is not None else PostgresStore()
        self.latest: OrderedDict[str, dict] = OrderedDict()
        self.jobs: OrderedDict[str, EvaluationJob] = OrderedDict()
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=queue_limit)
        self.history_limit = history_limit
        self.worker: asyncio.Task | None = None
        self.submit_lock = asyncio.Lock()
        self.job_keys: dict[str, str] = {}

    async def start(self):
        await self.store.open(list(self.samples.values()))
        saved = await self.store.latest()
        for raw in self.samples.values():
            envelope = saved.get(raw["claim_id"])
            if envelope is None or envelope["audit"]["mode"] == "replay-failed" and raw["claim_id"] in self.recordings:
                envelope = (await self.runner([raw], mode="rules", recordings=self.recordings))[0]
                self.validate_envelope(raw, envelope, "rules")
                await self.store.save_evaluation(envelope)
            else:
                self.validate_envelope(raw, envelope, envelope["audit"]["mode"].split("-")[0])
            self.latest[raw["claim_id"]] = copy.deepcopy(envelope)
        for payload in await self.store.jobs():
            job = EvaluationJob.model_validate(payload)
            self.jobs[job.job_id] = job
        self.worker = asyncio.create_task(self._consume(), name="reimbursement-worker")

    async def close(self):
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        await self.store.close()

    def snapshot(self) -> EvaluationSnapshot:
        return EvaluationSnapshot(evaluations=copy.deepcopy(list(self.latest.values())), policy_version=self.repository.version)

    def select(self, request: EvaluationRequest) -> list[dict]:
        if request.claims is not None:
            for claim in request.claims:
                if claim.claim_id in self.samples and claim != Claim.model_validate(self.samples[claim.claim_id]):
                    raise ValueError("Use a new claim_id for modified synthetic input")
            return [jsonable(c) for c in request.claims]
        ids = request.claim_ids or list(self.samples)
        unknown = set(ids) - self.samples.keys()
        if unknown:
            raise KeyError("Unknown sample claim ID")
        return [copy.deepcopy(self.samples[claim_id]) for claim_id in ids]

    async def submit(self, request: EvaluationRequest) -> EvaluationJob:
        claims = self.select(request)
        key = fingerprint({"claims": claims, "mode": request.mode})
        async with self.submit_lock:
            for existing_id, existing_key in self.job_keys.items():
                if existing_key == key and self.jobs[existing_id].status in {"queued", "running"}:
                    return self.jobs[existing_id].model_copy(deep=True)
            if self.queue.full():
                raise QueueFullError("Evaluation queue is full. Retry after the current job completes.")
            job = EvaluationJob(job_id=uuid4().hex, mode=request.mode,
                                claim_ids=[c["claim_id"] for c in claims], created_at=timestamp())
            await self.store.save_job(jsonable(job))
            self.jobs[job.job_id] = job
            self.job_keys[job.job_id] = key
            self.queue.put_nowait((job.job_id, claims))
            completed = [key for key, value in self.jobs.items() if value.status in {"completed", "failed"}]
            for old in completed[:max(0, len(self.jobs) - self.history_limit)]:
                del self.jobs[old]
                self.job_keys.pop(old, None)
            return job.model_copy(deep=True)

    def get_job(self, job_id: str) -> EvaluationJob:
        return self.jobs[job_id].model_copy(deep=True)

    def validate_envelope(self, raw: dict, envelope: dict, mode: str):
        claim = Claim.model_validate(raw)
        parsed = EvaluationEnvelope.model_validate(envelope)
        if parsed.claim != claim or parsed.result.claim_id != claim.claim_id:
            raise ValueError("Returned evaluation does not match the requested claim")
        if parsed.audit.get("mode") not in {mode, mode + "-failed"}:
            raise ValueError("Returned source does not match the selected mode")
        if not set(parsed.result.policy_refs).issubset(self.repository.rules):
            raise ValueError("Returned policy references are invalid")
        result = parsed.result
        pending = money(parsed.audit.get("pending_amount", 0))
        if result.decision == Decision.MANUAL_REVIEW:
            if result.approved_amount or result.deducted_amount or pending != claim.total_claimed:
                raise ValueError("Manual-review amounts must remain fully pending")
        elif result.approved_amount + result.deducted_amount != claim.total_claimed or pending:
            raise ValueError("Posted monetary amounts do not reconcile")
        actual = list(dict.fromkeys(e["name"] for e in parsed.audit.get("events", [])))
        if result.tools_used != actual or not set(actual).issubset(TOOL_NAMES):
            raise ValueError("Tool evidence does not match tools_used")
        ClaimResult.model_validate(result)

    async def _consume(self):
        while True:
            job_id, claims = await self.queue.get()
            job = self.jobs[job_id]
            job.status = "running"
            try:
                await self.store.save_job(jsonable(job))
                for raw in claims:
                    envelopes = await self.runner([raw], mode=job.mode, recordings=self.recordings)
                    if len(envelopes) != 1:
                        raise ValueError("Expected one evaluation per requested claim")
                    envelope = envelopes[0]
                    self.validate_envelope(raw, envelope, job.mode)
                    candidate = job.model_copy(deep=True)
                    candidate.evaluations.append(EvaluationEnvelope.model_validate(envelope))
                    candidate.completed_count += 1
                    await self.store.save_evaluation(envelope, jsonable(candidate))
                    job.evaluations = candidate.evaluations
                    job.completed_count = candidate.completed_count
                    # Custom API input can be exported without overwriting the five-claim dashboard.
                    if raw["claim_id"] in self.samples and Claim.model_validate(raw) == Claim.model_validate(self.samples[raw["claim_id"]]):
                        self.latest[raw["claim_id"]] = copy.deepcopy(envelope)
                job.status = "completed"
            except asyncio.CancelledError:
                job.status, job.error = "failed", "Evaluation interrupted by server shutdown."
                raise
            except Exception:
                # Operational UI/API failures retain earlier validated results.
                job.status, job.error = "failed", "Evaluation could not be completed. Earlier validated results remain available."
            finally:
                job.finished_at = timestamp()
                try:
                    await self.store.save_job(jsonable(job))
                except Exception:
                    job.status, job.error = "failed", "Database write failed. Earlier persisted results remain available."
                self.queue.task_done()
