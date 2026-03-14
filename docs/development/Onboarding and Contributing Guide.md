# Onboarding and Contributing Guide
## AWS Cost Optimizer

Welcome to AWS Cost Optimizer. This document will help you understand the project, get set up, and start contributing.

---

## 1. Project Overview

AWS Cost Optimizer is a desktop application that helps users reduce their S3 storage costs. It scans buckets, identifies optimization opportunities, scores them by risk, executes changes with safety guardrails, and supports rollback.

**Architecture:**
- **Backend:** Python FastAPI server (`server/`)
- **Frontend:** React + TypeScript SPA (`client/src/`)
- **Desktop Shell:** Tauri v2 / Rust (`client/src-tauri/`)
- **Bundling:** PyInstaller freezes the Python backend into a sidecar binary
- **Storage:** SQLite for run state and audit trails
- **Credentials:** OS keychain via Rust `keyring` crate

**Workflow:** Scan → Score → Execute → Rollback

---

## 2. Getting Started

### Prerequisites
- Python 3.11+ (3.13 recommended)
- Node.js 22+
- Rust stable (for Tauri desktop builds)
- AWS credentials with S3 read access (for real scanning)

### Backend Setup
```bash
cd server
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements-dev.txt
cp .env.example .env
make run  # Starts uvicorn on http://localhost:8000
```

### Frontend Setup
```bash
cd client
npm ci
npm run dev  # Starts Vite dev server on http://localhost:1420
```

### Desktop Dev Mode
```bash
cd client
npm run tauri -- dev  # Requires backend already running on :8000
```

### Running Tests
```bash
cd server
make test          # All tests
make test-unit     # Unit tests only
make test-integration  # Integration tests only
make test-cov      # With coverage (80% minimum enforced)
```

### Docker
```bash
cd server
make docker-run  # Builds and runs via docker-compose
```

---

## 3. Key Architectural Decisions

Detailed rationale is in `ADR - Architecture Decision Records.md`. Summary:

| Decision | Why |
|----------|-----|
| Desktop over web app | Credentials stay local, no server infrastructure |
| Tauri over Electron | 5 MB shell vs 150 MB, system WebView |
| SQLite over Postgres | Zero-config embedded DB, single-user workload |
| Weighted risk scoring | Five factors capture nuance better than simple thresholds |
| Progressive execution modes | Gradual trust building: dry_run → safe → standard → full |
| Pre-change state capture | Enables reliable rollback without guessing |
| PyInstaller sidecar | Users don't need Python installed |

---

## 4. Project Structure

```
aws-cost-optimizer/
├── server/
│   ├── app/
│   │   ├── main.py               # FastAPI app factory
│   │   ├── core/settings.py      # Configuration (env vars)
│   │   ├── models/contracts.py   # All Pydantic models and enums
│   │   ├── api/routes/optimizer.py  # API endpoints
│   │   ├── dependencies.py       # Singleton service instances
│   │   ├── scanner/service.py    # S3 bucket scanning
│   │   ├── scoring/service.py    # Risk scoring and savings calculation
│   │   ├── executor/service.py   # Action execution with guardrails
│   │   ├── executor/rollback.py  # Rollback service
│   │   └── state/store.py        # SQLite RunStore
│   ├── tests/
│   │   ├── conftest.py           # Shared fixtures (moto, tmp_store, client)
│   │   ├── unit/                 # 10 test files, 3,468 lines
│   │   └── integration/          # 7 test files, full workflow coverage
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── Makefile
│   └── requirements*.txt
├── client/
│   ├── src/
│   │   ├── App.tsx               # Routes, health check, update check
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx     # Run list, scan initiation
│   │   │   ├── RunDetail.tsx     # Score/execute/rollback workflow
│   │   │   ├── AuditTrail.tsx    # Execution audit with selective rollback
│   │   │   └── Settings.tsx      # AWS credential management
│   │   ├── api/client.ts         # Type-safe API client
│   │   ├── types.ts              # TypeScript interfaces (mirrors Pydantic)
│   │   └── components/           # StatusBadge, RiskBadge, ScanModal
│   ├── src-tauri/
│   │   ├── src/lib.rs            # Credential storage, sidecar management, updates
│   │   ├── tauri.conf.json       # Window config, CSP, updater, bundle settings
│   │   └── binaries/             # PyInstaller sidecar placed here at build time
│   ├── package.json
│   └── vite.config.ts
├── scripts/
│   ├── create_test_data.py       # S3 test data generator
│   ├── prepush_check.sh          # Pre-push validation
│   ├── build_desktop_app.sh      # One-command desktop build
│   └── merge_updater_latest.py   # Updater manifest for releases
└── .github/
    ├── workflows/
    │   ├── ci.yml                # Server tests + Docker build
    │   ├── desktop.yml           # Multi-platform Tauri builds
    │   └── release.yml           # Tagged release pipeline
    └── actions/
        └── desktop-prepare/      # Reusable action for sidecar + frontend setup
```

---

## 5. How to Contribute

### Where to Contribute

| Area | Skill Level | Files |
|------|-------------|-------|
| New recommendation types | Intermediate | `scanner/service.py`, `scoring/service.py`, `executor/service.py`, `contracts.py` |
| Scoring weight tuning | Beginner | `scoring/service.py` (WEIGHTS dict) |
| UI improvements | Beginner-Intermediate | `client/src/pages/`, `client/src/components/` |
| New AWS service scanners (EC2, RDS, etc.) | Advanced | New service module, new recommendation types |
| Test coverage expansion | Beginner | `tests/unit/`, `tests/integration/` |
| Documentation | Beginner | This folder |

### Contribution Workflow

1. Fork and clone the repository
2. Create a feature branch from `dev`: `git checkout -b feat/my-feature dev`
3. Make changes, add tests
4. Run the full test suite: `cd server && make test-cov`
5. Run the pre-push check: `bash scripts/prepush_check.sh --full`
6. Open a PR against `dev`

### Code Standards
- Python: Type hints on all function signatures, Pydantic models for all data contracts
- TypeScript: Strict mode enabled, no `any` types
- Tests: Every new feature needs unit tests. Integration tests for API changes.
- Coverage: Must maintain >= 80%

### Adding a New Recommendation Type

1. Add enum value to `RecommendationType` in `contracts.py`
2. Add scanner logic in `scanner/service.py` (detection method + integration into `_scan_bucket`)
3. Add risk factors in `scoring/service.py`:
   - `REVERSIBILITY_SCORES` entry
   - `_data_loss_risk()` case
   - `_calculate_savings()` handler
4. Add execution logic in `executor/service.py`:
   - `REQUIRED_PERMISSIONS` entry
   - `_execute_action()` handler
   - `_capture_pre_change_state()` and `_capture_post_change_state()` handlers
5. If reversible: add rollback handler in `rollback.py` and add to `REVERSIBLE_ACTIONS`
6. Add TypeScript type to `client/src/types.ts`
7. Add unit + integration tests

---

## 6. Future Features

### Planned
- **Multi-service support:** Extend beyond S3 to EC2 (unused instances, oversized instances), RDS (idle databases), EBS (unattached volumes)
- **Scheduling:** Periodic automated scans on a cron schedule
- **Cost history tracking:** Graph savings over time from executed optimizations
- **Batch approval workflow:** Select individual recommendations for approval before execution
- **Export/report generation:** PDF or CSV reports for stakeholders

### Possible Additions
- **PostgreSQL backend:** For multi-user web deployment
- **Role-based access control:** For team environments
- **Slack/email notifications:** Alert on new high-savings recommendations
- **Custom scoring weights:** User-configurable risk factor weights
- **Tag-based filtering:** Scan only resources with specific AWS tags
- **Cost Explorer integration:** Use AWS Cost Explorer data for more accurate savings estimates
- **Terraform/CloudFormation output:** Generate IaC for recommended changes

### Architecture Changes to Consider
- **Async S3 operations:** Replace synchronous boto3 with aioboto3 for non-blocking scans
- **WebSocket updates:** Push scan progress to the UI instead of polling
- **Plugin system:** Allow third-party recommendation providers

---

## 7. Test Plan and Results

### Test Strategy

| Layer | Tool | Coverage Target | What It Tests |
|-------|------|-----------------|---------------|
| Unit | pytest | >= 80% | Individual service methods, scoring formulas, state transitions |
| Integration | pytest + TestClient | Full workflow | API endpoints, request validation, error handling, end-to-end pipeline |
| AWS Mocking | moto | All S3 operations | Scanner, executor, rollback S3 interactions |

### Test Coverage by Service

| Service | Unit Test File(s) | Tests | Coverage Focus |
|---------|-------------------|-------|----------------|
| Scanner | `test_scanner.py` | 23 | Bucket resolution, lifecycle detection, age thresholds, multipart detection |
| Scoring | `test_scoring.py`, `test_scoring_boundaries.py` | 87+ | Weight calculation, risk levels, approval flags, savings formulas, exact boundary values |
| Executor | `test_executor.py`, `test_executor_edge.py` | 50+ | Mode resolution, eligibility, permissions, destructive guards, state capture, max_actions |
| Rollback | `test_rollback.py`, `test_rollback_edge.py` | 26+ | Eligibility, dry-run, action reversal, response integrity, all non-executed statuses |
| Store | `test_store.py`, `test_store_edge.py` | 35+ | CRUD, state transitions, audit tracking, empty inputs, rollback timestamp propagation |
| Settings | `test_settings.py` | 16 | CORS parsing, env var defaults |

### Integration Test Suites

| Suite | File | Tests | Validates |
|-------|------|-------|-----------|
| Scan Flow | `test_scan_flow.py` | 9 | POST /scan response structure, bucket filtering, persistence |
| Score Flow | `test_score_flow.py` | 8 | POST /score after scan, status transitions, error handling |
| Execute Flow | `test_execute_flow.py` | 11 | POST /execute modes, audit creation, state validation |
| Rollback Flow | `test_rollback_flow.py` | 8 | POST /rollback dry-run/live, selective rollback, audit updates |
| State Transitions | `test_state_transitions.py` | 24+ | Multi-step workflows, idempotency, error states |
| Runs API | `test_runs_api.py` | 18 | GET /runs, GET /runs/{id}, GET /runs/{id}/audit |
| Error Cases | `test_error_cases.py` | 11+ | Health endpoint, malformed requests, full pipeline |

### Test Fixtures

- **`aws_credentials`** (autouse): Sets fake AWS creds, prevents real API calls
- **`s3_mock`** (autouse): Wraps every test in moto's `mock_aws()` context with pre-populated test bucket
- **`clear_settings_cache`** (autouse): Clears LRU cache so env var changes take effect
- **`tmp_store`**: Fresh SQLite database per test (temp file, not `:memory:`)
- **`client`**: FastAPI TestClient with all dependencies mocked and injected
- **`no_permissions`**: Strips all executor permissions
- **`allow_destructive`** / **`deny_destructive`**: Controls destructive action gate

### Key Testing Patterns
- **Boundary value testing:** Exact threshold values (risk score 29→LOW, 30→MEDIUM, etc.)
- **Formula verification:** Expected values calculated with comments showing intermediate steps
- **Float comparison:** `pytest.approx()` with relative tolerance
- **State machine verification:** Full lifecycle tested with idempotency checks
- **Permission matrix:** Every recommendation type tested with and without required permissions

---

## 8. User Guide

### First Launch
1. Install the application (DMG on macOS, MSI/NSIS on Windows, DEB/AppImage on Linux)
2. On first launch, you'll be redirected to Settings
3. Enter your AWS credentials (Access Key ID, Secret Access Key, Region)
4. Click "Save Credentials" — they're stored in your OS keychain
5. Click "Test Connection" to verify
6. Navigate to the Dashboard

### Running a Scan
1. Click "New Scan" on the Dashboard
2. Optionally specify bucket filters (include/exclude)
3. Set max objects per bucket (default: 1,000)
4. Click "Scan" — the scan runs against your S3 account
5. Results appear as a new run in the Dashboard table

### Reviewing and Scoring
1. Click a run in the Dashboard to open Run Detail
2. Review the recommendations table (type, bucket/key, risk, savings)
3. Click "Score" in the right panel to run risk analysis
4. Review risk scores, confidence levels, and savings estimates

### Executing Recommendations
1. After scoring, choose an execution mode:
   - **Dry Run:** Preview only, no changes
   - **Safe:** Only low-risk, reversible, high-confidence actions
   - **Standard:** Low + medium risk actions
   - **Full:** All eligible actions
2. Set max actions (default: 100)
3. Optionally check "Dry Run" to force simulation regardless of mode
4. Click "Execute"
5. Review the execution summary (eligible, executed, skipped, blocked, failed)

### Rolling Back
1. On the Run Detail page, use the "Rollback All" button
2. Or navigate to the Audit Trail for selective rollback
3. Check "Dry Run" to preview rollback effects first
4. Select specific audit records to rollback individually
5. Click "Rollback Selected"

### Understanding Risk Levels
- **LOW (0-29):** Safe actions with high confidence. Often automatable.
- **MEDIUM (30-59):** Review recommended. May have moderate blast radius.
- **HIGH (60-100):** Requires approval. May involve data loss or large impact.

---

## 9. Changelog

### v1.0.0 (2025-02)

**Initial Release**

- **Scanner:** S3 bucket scanning for storage class optimization, lifecycle policies, multipart cleanup, stale object detection
- **Scoring Engine:** Five-factor weighted risk model with storage pricing matrix and break-even analysis
- **Executor:** Four execution modes (dry_run, safe, standard, full) with IAM permission validation and destructive action gating
- **Rollback:** Reversible action rollback with pre-change state capture, selective rollback by audit ID
- **State Management:** SQLite-backed persistence with complete audit trail
- **Desktop App:** Tauri v2 with React frontend, OS keychain credential storage, auto-updates
- **CI/CD:** Multi-version Python tests, multi-platform desktop builds, Docker smoke tests, release pipeline with code signing
- **Test Suite:** 245+ tests across unit and integration layers, 80%+ coverage enforced

**Commit History:**
| Commit | Description |
|--------|-------------|
| `b31e2a8` | S3 bucket scanner (storage class, lifecycle, multipart, stale objects) |
| `c77240a` | Risk scoring and dry-run mode |
| `1f5d431` | Execution with rollback |
| `f182af3` | Lambda functions |
| `4d3c0a9` | S3 test data script |
| `4645065` | Versioned optimizer API workflow |
| `07b84f2` | Weighted risk and savings scoring engine |
| `df2280c` | Durable run storage and action-level execution pipeline |
| `21d3186` | Rollback service with execution audit trail and state tracking |
| `d669360` | Full test suite, CI, and local dev tooling |
| `c2d4604` | Replace Next.js with Tauri v2 desktop app |
| `c0a595e` | Release pipeline and auto-updater |
| `d87a5c2` | Updated gitignore |
