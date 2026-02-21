# Server API

FastAPI backend for the AWS Cost Optimizer workflow.

## Run

```bash
cd server
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

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

- `GET /api/v1/optimizer/runs`
  - Returns run summaries.

- `GET /api/v1/optimizer/runs/{run_id}`
  - Returns full run details.

## Typical Flow

1. Call `/optimizer/scan`
2. Call `/optimizer/score` with `run_id`
3. Call `/optimizer/execute` with same `run_id`
4. Poll `/optimizer/runs/{run_id}` if needed

## CORS

Configured by `CORS_ORIGINS` env var.

Default:

- `http://localhost:3000`
- `http://127.0.0.1:3000`

