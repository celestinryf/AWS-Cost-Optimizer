# AWS Cost Optimizer

AWS Cost Optimizer is a desktop-first workflow for identifying and executing S3 cost-saving recommendations.

It combines:
- A `FastAPI` backend (`server/`) that scans, scores, executes, and rolls back optimization actions.
- A `React + Vite` frontend (`client/`) for reviewing recommendations and run history.
- A `Tauri` desktop shell (`client/src-tauri/`) that bundles the frontend and a Python sidecar API binary.

## Repository layout

- `client/` - React frontend and Tauri desktop app.
- `server/` - FastAPI backend, tests, and PyInstaller spec for sidecar bundling.
- `scripts/` - helper scripts (test data generator, pre-push CI checklist).
- `.github/workflows/` - CI, desktop build matrix, and release workflows.

## Core workflow

1. `POST /optimizer/scan` creates a run and recommendations.
2. `POST /optimizer/score` applies risk/confidence/impact scoring.
3. `POST /optimizer/execute` applies changes (or dry-run).
4. `POST /optimizer/rollback` can undo eligible executed actions.

API base URL in local/dev mode: `http://127.0.0.1:8000/api/v1`

## Prerequisites

- Node.js 22+
- Python 3.11+ (3.13 is used in CI desktop/release workflows)
- Rust stable toolchain (`cargo`, `rustup`) for Tauri builds
- On Linux desktop builds: WebKitGTK and related Tauri system deps

## Local development

### 1) Run backend API

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 2) Run frontend web UI

```bash
cd client
npm ci
npm run dev
```

Vite dev server runs on `http://localhost:1420` and calls the backend at `127.0.0.1:8000`.

### 3) Run Tauri desktop app (dev)

Start the backend first, then:

```bash
cd client
npm run tauri -- dev
```

In dev mode, Tauri does not auto-spawn the backend sidecar; it expects the API to already be running.

## Testing and checks

### Backend tests

```bash
cd server
make test-unit
make test-integration
make test-cov
```

### Frontend build

```bash
npm --prefix client run build
```

### Pre-push checklist

```bash
bash scripts/prepush_check.sh --full
```

For local desktop packaging verification:

```bash
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD='your-password'
bash scripts/prepush_check.sh --desktop-build
```

## Desktop build and release

Desktop CI workflow: [`.github/workflows/desktop.yml`](/Users/jideryf/AWS-Cost-Optimizer/.github/workflows/desktop.yml)  
Release workflow: [`.github/workflows/release.yml`](/Users/jideryf/AWS-Cost-Optimizer/.github/workflows/release.yml)

Required GitHub secrets for signed updater artifacts:
- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`

Notes:
- `TAURI_SIGNING_PRIVATE_KEY` must be the exact key contents on one line, without extra newlines.
- `GITHUB_TOKEN` alone is not sufficient for updater signing.

## Helpful scripts

- `scripts/create_test_data.py` - seeds an S3 bucket with sample data for scanner testing.
- `scripts/prepush_check.sh` - validates key CI/build checks before pushing.
