# Server API

FastAPI backend for the AWS Cost Optimizer workflow.

## Run

```bash
cd server
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Dependency lockfiles

Direct dependency sources:

- `requirements.in`
- `requirements-dev.in`
- `requirements-bundle.in`

Compiled lockfiles:

- `requirements.txt`
- `requirements-dev.txt`
- `requirements-bundle.txt`

Regenerate and verify:

```bash
make deps-lock
make deps-check
```

Run data is persisted in SQLite at `data/runs.db` by default.

## Base URL

- Local: `http://localhost:8000`
- API prefix: `/api/v1`

## Endpoints

- `GET /api/v1/health`
  - Liveness and environment details.

- `POST /api/v1/optimizer/scan`
  - Creates a run and returns recommendations.

- `POST /api/v1/optimizer/score`
  - Scores an existing run.

- `POST /api/v1/optimizer/execute`
  - Executes (or dry-runs) a scored run.
  - Modes: `dry_run`, `safe`, `standard`, `full`
  - Returns action-level results including `executed`, `skipped`, `blocked`, and `failed` items.

- `GET /api/v1/optimizer/runs`
  - Returns run summaries.

- `GET /api/v1/optimizer/runs/{run_id}`
  - Returns full run details.

- `GET /api/v1/optimizer/runs/{run_id}/audit`
  - Returns execution audit trail (action status, pre/post state, rollback metadata).

- `POST /api/v1/optimizer/rollback`
  - Rolls back eligible actions from an execution batch.
  - Supports targeted rollback via `audit_ids`.
  - Supports `dry_run` to preview rollback results.

## Typical Flow

1. Call `/optimizer/scan`
2. Call `/optimizer/score` with `run_id`
3. Call `/optimizer/execute` with same `run_id`
4. Poll `/optimizer/runs/{run_id}` if needed

## Execution Guardrails

- Permission checks use `EXECUTOR_GRANTED_PERMISSIONS` (comma-separated IAM-style actions).
- Destructive delete actions require `ALLOW_DESTRUCTIVE_EXECUTION=true`.
- `dry_run` validates execution eligibility and permissions without mutating resources.

## Persistence

- Run state is durable across restarts via SQLite.
- Override DB location with `RUNS_DB_PATH`.
  - Example: `RUNS_DB_PATH=/var/lib/cost-optimizer/runs.db`

## CORS

Configured by `CORS_ORIGINS` env var.

Default:

- `http://localhost:3000`
- `http://127.0.0.1:3000`
