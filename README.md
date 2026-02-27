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

### Dependency lock workflow

The Python dependency source of truth is:

- `server/requirements.in` (runtime direct dependencies)
- `server/requirements-dev.in` (dev/test/tooling direct dependencies)
- `server/requirements-bundle.in` (desktop sidecar bundle direct dependencies)

Compiled lockfiles remain committed:

- `server/requirements.txt`
- `server/requirements-dev.txt`
- `server/requirements-bundle.txt`

Regenerate and verify:

```bash
make -C server deps-lock
make -C server deps-check
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

### One-command desktop installer build

Signed build (produces updater artifacts + signed installer):

```bash
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD='your-password'
bash scripts/build_desktop_app.sh
```

Unsigned local build (installer only, skips updater signing):

```bash
bash scripts/build_desktop_app.sh --unsigned
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

## Downloads

- Latest Release (all installers): https://github.com/celestinryf/AWS-Cost-Optimizer/releases/latest
- All Releases (pick any version): https://github.com/celestinryf/AWS-Cost-Optimizer/releases

Direct download link pattern (replace `vX.Y.Z` and filename):

```text
https://github.com/celestinryf/AWS-Cost-Optimizer/releases/download/vX.Y.Z/<asset-filename>
```

Examples:
- macOS DMG: `https://github.com/celestinryf/AWS-Cost-Optimizer/releases/download/vX.Y.Z/AWS.Cost.Optimizer_<version>_aarch64.dmg`
- Windows MSI: `https://github.com/celestinryf/AWS-Cost-Optimizer/releases/download/vX.Y.Z/AWS.Cost.Optimizer_<version>_x64_en-US.msi`
- Linux AppImage: `https://github.com/celestinryf/AWS-Cost-Optimizer/releases/download/vX.Y.Z/AWS.Cost.Optimizer_<version>_amd64.AppImage`

Known issue:
- `v1.0.2` macOS assets were signed incorrectly and may show as damaged.
- `v1.0.3` release is incomplete (missing macOS/Windows installers). Use `v1.0.4+`.

Detailed per-platform CLI commands: `docs/downloads.md`

## Helpful scripts

- `scripts/create_test_data.py` - seeds an S3 bucket with sample data for scanner testing.
- `scripts/prepush_check.sh` - validates key CI/build checks before pushing.
- `scripts/build_desktop_app.sh` - one-command desktop installer build (deps + sidecar + Tauri package).
- `scripts/lib/desktop_common.sh` - shared shell helpers for desktop/pre-push scripts.
- `scripts/update_homebrew_cask.sh` - generates a Homebrew cask from release assets.
- `scripts/generate_winget_manifests.sh` - generates WinGet manifests from release assets.
- `scripts/merge_updater_latest.py` - collects and merges updater fragments into `latest.json`.

## Documentation

- `docs/pre-push-checklist.md` - pre-push quality gate usage.
- `docs/context-strategy.md` - architecture context and roadmap decisions (Terraform, multi-cloud, scale).
- `docs/distribution.md` - release targets and package-manager publishing flow.
- `docs/downloads.md` - how users can download specific versions per platform.
