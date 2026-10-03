# Travel Reimbursement Approval Agent

A local reimbursement workspace that combines deterministic policy checks with a LangChain agent, Ollama, and MCP tools. FastAPI serves the backend, React and TypeScript provide the interface, and PostgreSQL stores claims, evaluation history, and job state.

This repository contains the **companion application**. The original single-notebook assignment submission is maintained separately in [Travel-Reimbursement-Approval-Agent-New](https://github.com/SHASWATprakash/Travel-Reimbursement-Approval-Agent-New).

## What the application provides

- **Overview:** monetary summaries, decision distribution, claim search, filtering, and JSON export.
- **Claim detail:** receipts, line-item calculations, findings, policy citations, and evaluation controls.
- **Manual review:** pending amounts, reason codes, and a reviewer checklist.
- **Policy and audit:** twelve policy rules, actual MCP tool arguments and outputs, model proposals, and validation evidence.
- **28 synthetic claims**, identified as `DEMO-001` through `DEMO-028`, independent of the assignment's five claims.
- PostgreSQL persistence and asynchronous evaluation jobs with progress polling.

All employee identities and companion claims are synthetic. The application recommends decisions; it does not authorize payments or record reviewer approvals.

## Execution modes

| Mode | Behavior | Requirements |
| --- | --- | --- |
| **Rules** — default | Executes the six policy tools through MCP in a fixed order. Produces an explicitly labelled deterministic baseline. No model inference or model-selected tools. | Backend and PostgreSQL |
| **Live** | LangChain/Ollama selects tools, consumes their evidence, and submits a structured recommendation for independent validation. | Backend, PostgreSQL, and the configured local Ollama model |
| **Replay** | Replays genuine captured model messages, executes the MCP tools again, and verifies the context and results. Performs no fresh inference. | Backend, PostgreSQL, and a matching recording |

The repository includes genuine recordings for **15 of the 28 companion claims**: `DEMO-001`–`DEMO-007`, `DEMO-009`–`DEMO-014`, `DEMO-016`, and `DEMO-017`. Replay of an uncaptured or modified claim produces an explicit manual-review hold. It does not silently switch to Live or Rules.

Displayed results retain their execution source when the selected mode changes. On startup, the application restores persisted evaluations and creates Rules baselines for new demo claims.

## Prerequisites

- Python **3.11–3.13**; the development verification used Python 3.12.13.
- Node.js **22.12 or newer** and npm.
- Docker with Docker Compose v2 for the supplied PostgreSQL setup, or an existing compatible PostgreSQL server.
- Ollama only if you want Live mode.

No OpenAI API key is required. PostgreSQL is required in all modes.

## Setup

### 1. Clone and configure

```bash
git clone https://github.com/SHASWATprakash/Travel-Reimbursement-Approval-Agent.git
cd Travel-Reimbursement-Approval-Agent
cp .env.example .env
```

If you already have the repository, start from its root directory and create `.env` only if it does not exist. `.env` is ignored by Git.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://travel_app:travel_local_only@127.0.0.1:5433/travel_companion` | SQLAlchemy/asyncpg database connection |
| `TRAVEL_MODEL` | `qwen3.5:4b` | Local model for Live mode |
| `TRAVEL_AGENT_TIMEOUT_SECONDS` | `120` | Overall per-claim agent deadline; allowed range 5–120 seconds |
| `TRAVEL_FRONTEND_DIST` | `frontend/dist`, resolved from the launch directory | Optional built frontend directory served by FastAPI |

The supplied password is a local demo credential. If you change `POSTGRES_PASSWORD` for Docker Compose, update the password in `DATABASE_URL` to match.

### 2. Start PostgreSQL

From the repository root, with Docker running:

```bash
docker compose up -d --wait postgres
docker compose ps
```

Compose exposes PostgreSQL on `127.0.0.1:5433` and preserves data in the `travel_postgres` named volume. The backend creates its initial tables and seeds the synthetic claims on first startup. No separate seed command is needed.

If a PostgreSQL instance already uses port 5433, use that instance with the correct `DATABASE_URL`, or change the Compose port and connection URL together.

### 3. Install the backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install -e .
```

Use your Python 3.11–3.13 executable if `python3.12` is unavailable. The lock file includes the backend test dependencies and SQLAlchemy's `greenlet` async dependency.

### 4. Install the frontend

In another terminal, from the repository root:

```bash
cd frontend
npm ci
```

## Run the application

Keep both application terminals running.

**Terminal 1 — backend**, starting from the repository root:

```bash
cd backend
source .venv/bin/activate
python -m uvicorn travel_agent.api:app --host 127.0.0.1 --port 8000 --reload --env-file ../.env
```

**Terminal 2 — frontend**, starting from the repository root:

```bash
npm run dev
```

The root script delegates to the frontend. You can also run `npm run dev` inside `frontend/`.

| Address | Purpose |
| --- | --- |
| http://127.0.0.1:5173 | React interface |
| http://127.0.0.1:8000/docs | Interactive API documentation |
| http://127.0.0.1:8000/api/v1/health | API status and local-model availability |

Vite forwards `/api` requests to the backend on port 8000. The initial workspace should contain **28 claims and 12 policy rules**.

### Enable Live mode

Install Ollama, then run:

```bash
ollama pull qwen3.5:4b
ollama serve
```

If Ollama is already running through its desktop application, a second `ollama serve` process is unnecessary. The agent connects to local Ollama on port 11434.

Select **Live** and evaluate one claim first. Claims execute serially to limit local model memory contention. Evaluating all 28 claims can take several minutes; the interface polls job progress while the backend works. The agent has a six-turn budget, twelve business-tool executions, and an overall deadline per claim.

### Suggested walkthrough

1. Open the overview and confirm the 28 synthetic scenarios.
2. Inspect `DEMO-005`: the $560 hotel claim has $400 allowed and $160 deducted in Rules mode.
3. Inspect `DEMO-009`: the missing airfare receipt holds the full $340 for manual review.
4. Open Policy & audit to inspect citations and the six executed MCP tools.
5. Select `DEMO-001` and compare its Rules baseline with Replay or a fresh Live evaluation.
6. Export the results as JSON.

## Architecture and decision control

```text
React / TypeScript / TanStack Query
                  |
             FastAPI API
                  |
       Bounded evaluation job queue
                  |
      Rules / Live / Replay workflow
                  |
         MCP policy tools
                  |
    Decimal calculations + result validation
                  |
    PostgreSQL claims, jobs, and evaluation evidence
```

The Python code uses small classes for policy access, evaluation, tool execution, agent control, validation, job management, and persistence. PostgreSQL JSONB records preserve the structured claims and audit envelopes; monetary calculations use Python `Decimal`.

The six tools are `lookup_policy`, `check_eligibility`, `check_receipts`, `calculate_limits`, `check_approval_threshold`, and `check_timeliness`. MCP uses the official Python SDK's in-process memory transport. Live model recommendations cannot bypass policy checks or independently determine monetary amounts.

Possible decisions are `APPROVE`, `PARTIAL_APPROVE`, `REJECT`, and `MANUAL_REVIEW`. Missing required receipts, exceptions, ambiguity, conflicting information, and unresolved agent failures require manual review. For those claims, approved and deducted amounts are zero and the entire claim remains pending. Provisional calculations remain separate in audit metadata.

Exports contain exactly nine fields:

```text
claim_id, decision, approved_amount, deducted_amount, missing_docs,
policy_refs, confidence, explanation, tools_used
```

Stable reason codes appear in the explanation and audit metadata. Pending amounts belong to the dashboard/audit envelope. Confidence is a documented support heuristic, not a calibrated reimbursement probability.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | API and Ollama availability |
| GET | `/api/v1/policies` | Rules, limits, and tool names |
| GET | `/api/v1/sample-claims` | Synthetic claim inputs and scenario labels |
| GET | `/api/v1/evaluations/latest` | Latest dashboard evaluations |
| POST | `/api/v1/evaluations` | Submit an evaluation job; returns HTTP 202 |
| GET | `/api/v1/evaluations/{job_id}` | Job status and results |

For example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/evaluations \
  -H 'Content-Type: application/json' \
  -d '{"mode":"rules","claim_ids":["DEMO-005"]}'
```

Use the returned `job_id` to retrieve the job. Add `?include_results=false` for lightweight progress polling. Omitting the claim selection evaluates all demo claims. Alternatively, provide a `claims` array of validated claim JSON; modified inputs must use a new ID instead of overwriting a seeded claim.

One worker processes jobs. The queue accepts four waiting jobs, coalesces identical active submissions, and returns HTTP 429 when full. Evaluations and job progress are persisted transactionally. On restart, unfinished jobs are marked failed rather than reported as completed. Custom claim results are available in their job response; the dashboard remains the fixed synthetic scenario collection.

## Tests and build

From the repository root, with the backend virtual environment active:

```bash
cd backend
python -m pytest -q
```

PostgreSQL integration tests require a **dedicated test database**. Create it once:

```bash
# Run from the repository root.
docker compose exec postgres createdb -U travel_app travel_companion_test
```

Then, from `backend/` with its virtual environment active:

```bash
export TEST_DATABASE_URL='postgresql+asyncpg://travel_app:travel_local_only@127.0.0.1:5433/travel_companion_test'
python -m pytest -q
```

The integration tests reset tables in that test database. They enforce the `_test` database-name suffix; do not point them at your application database.

Build the frontend from the repository root:

```bash
npm run build
```

To serve the built interface through FastAPI from the repository root:

```bash
backend/.venv/bin/python -m uvicorn travel_agent.api:app \
  --host 127.0.0.1 --port 8000 --env-file .env
```

Open http://127.0.0.1:8000. This is a local build demonstration, not a production deployment configuration.

### Current verification status

- Backend development verification: **74 tests passed**, including actual PostgreSQL persistence tests and the 28-scenario acceptance matrix.
- Frontend TypeScript check and production build passed.
- A separate development browser harness passed six of seven checks: overview/export, claim deductions/citations, review queue, MCP/policy inspection, reevaluation/source labels, and API error handling. The mobile overflow check remains unresolved.
- Browser test configuration is not currently included in this repository; the existing `test:e2e` script is not a ready-to-run verification gate yet.
- Database verification used local PostgreSQL 14.18; the supplied Compose configuration uses PostgreSQL 17. The Compose-based setup has not been independently exercised in that verification.
- The original assignment's five claims remain policy/agent regression fixtures and are not the companion dashboard dataset.

## Troubleshooting

**`npm error Missing script: "dev"`**

Run npm in this companion repository or its `frontend/` directory. The separate notebook submission folder has no frontend scripts. From the companion root, `npm --prefix frontend run dev` also works.

**`pip install` requires an argument**

Use `python -m pip install -r requirements.lock` inside `backend/`, followed by `python -m pip install -e .`.

**`ModuleNotFoundError: greenlet`**

Stop the backend, activate `backend/.venv`, and reinstall the lock file:

```bash
python -m pip install -r requirements.lock
python -c "import greenlet; print(greenlet.__version__)"
```

Restart the backend afterward. The project's `sqlalchemy[asyncio]` dependency and lock file include `greenlet`; installing it into another Python environment will not fix the running server.

**Only five claims are visible**

Confirm that the backend is running from this companion checkout. `/api/v1/sample-claims` and `/api/v1/evaluations/latest` should both return 28 entries. Restart the backend after updating dependencies and refresh the browser to clear the previous query cache.

**Database connection or Unicode errors**

Check `docker compose ps`, the port, and `DATABASE_URL`. Use a UTF8 database for Unicode policy text and audit evidence. An existing SQL_ASCII database needs a separate UTF8 database and data migration; changing the client encoding alone is insufficient.

**Live mode is unavailable or fails**

Check `ollama list`, the configured model name, and the local service on port 11434. Timeouts and unvalidated recommendations result in explicit manual-review holds. Rules remains available without Ollama. Recorded runs do not prove that every future Live run will succeed.

## Scope and limitations

This is a local prototype. It has no authentication, payment integration, OCR, or document upload pipeline. Receipt flags are supplied structured data. The initial database schema is created idempotently; future schema changes need migrations. The implementation assumes one API process with one evaluation worker, not distributed job coordination.

Next improvements include the mobile layout fix, a committed browser test harness, schema migrations, broader live-model evaluation, and a separate learning track. Runtime caches, credentials, and generated build files should remain outside source commits.
