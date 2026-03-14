# Software Requirements Specification (SRS)
## AWS Cost Optimizer

**Version:** 1.0.0
**Last Updated:** 2026-03-05
**Author:** Celestin Ryf

---

## 1. Project Description

AWS Cost Optimizer is a full-stack desktop application that scans Amazon S3 buckets, identifies cost-saving opportunities, scores them by risk and potential savings, executes optimization actions with safety guardrails, and supports rollback of reversible changes. It packages a Python FastAPI backend as a sidecar binary inside a Tauri v2 desktop shell, delivering a single-install experience with no cloud infrastructure required beyond the user's own AWS account.

### 1.1 Problem Statement

AWS S3 storage costs grow silently. Objects accumulate in expensive storage classes long after they stop being accessed, lifecycle policies go unconfigured, and incomplete multipart uploads consume space indefinitely. Manual auditing is tedious, error-prone, and doesn't scale across dozens of buckets with millions of objects.

### 1.2 Solution

A desktop application that automates the scan-score-execute-rollback lifecycle:
1. **Scan** — Discover S3 objects that are candidates for optimization (cold objects in STANDARD, missing lifecycle policies, stale multipart uploads, very old objects).
2. **Score** — Apply a weighted risk model and savings calculator to each recommendation, producing approval/automation guidance.
3. **Execute** — Apply changes in progressive safety modes (dry-run, safe, standard, full) with IAM permission validation and destructive-action gating.
4. **Rollback** — Reverse eligible actions using captured pre-change state.

---

## 2. Tools and Technology Stack

### 2.1 Backend

| Tool | Version | Why Chosen |
|------|---------|------------|
| **Python** | 3.11–3.13 | Mature AWS SDK (boto3), rapid prototyping, strong typing via Pydantic |
| **FastAPI** | 0.128.0 | Async-capable, automatic OpenAPI docs, Pydantic-native request validation |
| **Uvicorn** | 0.40.0 | ASGI server, lightweight, single-worker mode compatible with SQLite |
| **Pydantic** | 2.12.5 | Data validation, serialization, and contract enforcement between layers |
| **Boto3** | 1.42.24 | Official AWS SDK — S3 operations, paginator support, error typing |
| **SQLite** | stdlib | Zero-dependency persistence, embedded in the sidecar, no external DB needed |
| **PyInstaller** | — | Freezes the Python runtime + dependencies into a single executable for Tauri |

**Why Python over Node/Go/Rust for the backend?**
- Boto3 is the most complete AWS SDK, with paginator patterns, waiter support, and error code enums.
- Pydantic v2 gives compile-time-like safety at runtime with minimal boilerplate.
- FastAPI auto-generates OpenAPI specs, which keeps the API self-documenting.
- Python's prototyping speed was critical for rapid iteration on the scoring algorithm.
- Tradeoff: Python is slower than Go/Rust for CPU-bound work, but the bottleneck here is S3 API latency, not computation.

### 2.2 Frontend

| Tool | Version | Why Chosen |
|------|---------|------------|
| **Tauri v2** | 2.0.0 | Small binary (~5 MB shell vs Electron's ~150 MB), native OS integration, Rust security model |
| **React** | 19.0.0 | Component model fits the dashboard/detail/audit page structure |
| **TypeScript** | 5.0.0 | Type safety across the client, mirrors Pydantic contracts |
| **Vite** | 6.0.0 | Fast HMR, ESM-native, minimal config |
| **React Router** | 7.0.0 | Client-side routing for SPA navigation |

**Why Tauri over Electron?**
- Binary size: Tauri ships a ~5 MB Rust shell + system WebView vs Electron bundling Chromium (~150 MB).
- Security: Tauri's CSP and capability model restrict what the frontend can access.
- Performance: Native webview uses less RAM than a separate Chromium process.
- Tradeoff: Tauri v2 is newer with a smaller ecosystem, and WebView behavior varies across OS versions. Cross-platform testing is more important.

**Why a desktop app instead of a web app?**
- AWS credentials stay local — never transmitted to a third-party server.
- The sidecar pattern bundles the backend, so users don't need Python, pip, or Docker.
- Offline-capable for environments with restricted outbound access.

### 2.3 Infrastructure & CI

| Tool | Purpose |
|------|---------|
| **GitHub Actions** | CI/CD — test matrix (Python 3.11-3.13), Docker build smoke tests, multi-platform desktop builds |
| **Docker** | Server containerization for production deployment alternative |
| **Moto** | AWS service mocking for tests (no real AWS calls in CI) |
| **pytest + pytest-cov** | Test runner with 80% minimum coverage enforcement |
| **pip-tools** | Deterministic dependency locking (`.in` → `.txt` compilation) |

### 2.4 Credential Storage

| Platform | Mechanism |
|----------|-----------|
| **macOS** | Keychain (via `keyring` crate) |
| **Windows** | Credential Manager (via `keyring` crate) |
| **Linux** | Secret Service / libsecret (via `keyring` crate) |

Credentials are stored in the OS-native secure store under service `aws-cost-optimizer`, account `aws-credentials`. They are never written to disk in plaintext.

---

## 3. Expected Throughput and Scale

### 3.1 Target Users

**Primary:** Individual developers, DevOps engineers, and small platform teams (1-5 users) managing AWS S3 costs for their organization.

**Not designed for:** Multi-tenant SaaS, enterprise-wide deployment with hundreds of concurrent users, or real-time streaming optimization.

### 3.2 Data Volume

| Dimension | Expected Range | Design Limit |
|-----------|----------------|--------------|
| Buckets per scan | 1–50 | Configurable via include/exclude filters |
| Objects per bucket | Up to 100,000 | `max_objects_per_bucket` parameter (default: 1,000, max: 100,000) |
| Recommendations per run | 10–5,000 | Limited by object count |
| Concurrent runs | 1 (single-user desktop) | SQLite single-writer |
| Historical runs | Dozens to low hundreds | SQLite handles this easily |
| Audit records | 1 per executed action | Grows linearly with executions |

### 3.3 Read/Write Patterns

| Operation | Frequency | I/O Type |
|-----------|-----------|----------|
| Scan (S3 API) | On-demand, minutes apart | Heavy S3 reads (ListObjects, GetLifecycle, ListMultipartUploads) |
| Score (CPU) | After each scan | Pure computation, no I/O |
| Execute (S3 API) | On-demand, after review | S3 writes (CopyObject, PutLifecycle, AbortMultipart, DeleteObject) |
| Dashboard poll | Every 30 seconds | Light SQLite read |
| Health check | Every 10 seconds | No I/O (returns static response) |

### 3.4 Database Sizing

SQLite is appropriate for this workload because:
- Single writer (one desktop user, one Uvicorn worker)
- Read-heavy after initial write (poll runs list, view details)
- Data volume is small (KB to low MB for JSON payloads)
- No concurrent multi-user access

**Migration trigger:** If the project evolves to a shared web service with multiple concurrent users, migrate to PostgreSQL. The `RunStore` abstraction makes this a drop-in replacement.

---

## 4. Architecture Decisions and Tradeoffs

### 4.1 SQLite over PostgreSQL
- **Chose:** SQLite — zero-config, embedded in the sidecar binary, no external service.
- **Tradeoff:** Single-writer limitation, no concurrent multi-user access.
- **Mitigation:** Single Uvicorn worker (`--workers 1`), thread-safe locking in `RunStore`.

### 4.2 Sidecar Pattern over Embedded Python
- **Chose:** PyInstaller-frozen sidecar binary spawned by Tauri as a subprocess.
- **Tradeoff:** Larger bundle size (~50 MB for the Python runtime), startup latency (5-10s).
- **Mitigation:** Health-check polling on startup, loading indicator in the UI, 10-15s timeout with retry.

### 4.3 Deterministic Scanner for Testing
- **Chose:** Scanner service that calls real S3 APIs, with full moto mocking in tests.
- **Tradeoff:** Tests don't exercise real AWS rate limits or eventual consistency.
- **Mitigation:** `create_test_data.py` script for manual integration testing against real S3.

### 4.4 Weighted Risk Scoring over Simple Thresholds
- **Chose:** Five-factor weighted model (reversibility 30%, data_loss 25%, age_confidence 20%, size_impact 15%, access_confidence 10%).
- **Tradeoff:** More complex to understand and tune than a simple high/medium/low classification.
- **Mitigation:** Factor scores are exposed in the API and UI, making the scoring transparent.

### 4.5 Progressive Execution Modes
- **Chose:** Four execution modes (dry_run → safe → standard → full) rather than a binary execute/don't-execute.
- **Tradeoff:** More UI complexity, more code paths to test.
- **Mitigation:** Default to dry_run, clear mode descriptions in the UI, comprehensive test coverage of mode eligibility.

### 4.6 Pre-Change State Capture for Rollback
- **Chose:** Capture full pre-change state (storage class, lifecycle rules) before every mutation.
- **Tradeoff:** Slightly more S3 API calls and larger audit records.
- **Mitigation:** State is captured only for actions that actually execute, not during dry-run.

### 4.7 OS Keychain for Credentials
- **Chose:** Platform-native secure storage via the `keyring` Rust crate.
- **Tradeoff:** Platform-specific behavior, harder to test in CI.
- **Mitigation:** Legacy file migration path, fallback handling in the Rust setup hook.

---

## 5. Functional Requirements

### 5.1 Scanning
- FR-1: System shall scan S3 buckets and identify objects in STANDARD storage class that haven't been modified in 90+ days.
- FR-2: System shall detect buckets without lifecycle policies.
- FR-3: System shall detect incomplete multipart uploads older than 7 days.
- FR-4: System shall detect objects older than 365 days as stale deletion candidates.
- FR-5: System shall support include/exclude bucket filters and per-bucket object limits.

### 5.2 Scoring
- FR-6: System shall calculate a weighted risk score (0-100) for each recommendation.
- FR-7: System shall estimate monthly savings using a storage class pricing matrix.
- FR-8: System shall calculate break-even days for storage class transitions.
- FR-9: System shall flag recommendations requiring human approval (risk >= 55, deletions, objects >= 10 GB).
- FR-10: System shall identify recommendations safe to automate (risk < 30, confidence >= 70, non-destructive).

### 5.3 Execution
- FR-11: System shall support four execution modes: dry_run, safe, standard, full.
- FR-12: System shall validate IAM permissions before attempting each action.
- FR-13: System shall block destructive actions (DELETE_STALE_OBJECT) unless explicitly enabled.
- FR-14: System shall capture pre-change and post-change state for every executed action.
- FR-15: System shall support a configurable max_actions limit per execution.

### 5.4 Rollback
- FR-16: System shall support rolling back CHANGE_STORAGE_CLASS and ADD_LIFECYCLE_POLICY actions.
- FR-17: System shall support selective rollback by audit ID.
- FR-18: System shall support dry-run rollback to preview effects.
- FR-19: System shall restore original lifecycle rules (or remove them entirely if none existed).

### 5.5 State Management
- FR-20: System shall persist run state across application restarts (SQLite).
- FR-21: System shall maintain a complete audit trail with timestamps for every action.
- FR-22: System shall track run status transitions: scanned → scored → executed.

### 5.6 Desktop Application
- FR-23: Application shall store AWS credentials in the OS-native secure keychain.
- FR-24: Application shall bundle the backend as a sidecar binary (no Python installation required).
- FR-25: Application shall support auto-updates via GitHub Releases.
- FR-26: Application shall redirect to settings on first launch if no credentials are stored.

---

## 6. Non-Functional Requirements

- NFR-1: Test coverage shall be >= 80% (enforced in CI).
- NFR-2: Application shall build on macOS (aarch64, x86_64), Windows (x86_64), and Linux (x86_64).
- NFR-3: Backend startup shall complete within 15 seconds.
- NFR-4: CSP shall restrict API connections to `http://127.0.0.1:8000` only.
- NFR-5: No AWS credentials shall be written to disk in plaintext.
- NFR-6: Docker image shall run as a non-root user.
- NFR-7: CI shall test against Python 3.11, 3.12, and 3.13.

---

## 7. System Context Diagram

```
+-------------------+         +-------------------+         +----------------+
|   Tauri Desktop   |  HTTP   |  FastAPI Backend   |  AWS    |   Amazon S3    |
|   (React + Rust)  |-------->|  (Python Sidecar)  |-------->|   Buckets      |
|                   |  :8000  |                    |  SDK    |                |
+-------------------+         +-------------------+         +----------------+
        |                             |
        |  OS Keychain                |  SQLite
        v                             v
+-------------------+         +-------------------+
|  Credential Store |         |  data/runs.db     |
|  (keyring crate)  |         |  (runs + audit)   |
+-------------------+         +-------------------+
```
