# Architecture Overview
## AWS Cost Optimizer

---

## 1. System Context

```
                          +---------------------------+
                          |        End User           |
                          |   (DevOps / Engineer)     |
                          +-------------+-------------+
                                        |
                                   Launches
                                        |
                                        v
+-----------------------------------------------------------------------+
|                        Desktop Application                            |
|                                                                       |
|  +-------------------+    HTTP :8000    +---------------------------+ |
|  |   Tauri Shell     |---------------->|   FastAPI Backend          | |
|  |   (Rust)          |<----------------|   (Python Sidecar)        | |
|  |                   |                 |                           | |
|  |  - Window mgmt    |                 |  - Scanner Service        | |
|  |  - Credential     |                 |  - Scoring Service        | |
|  |    storage         |                 |  - Execution Service      | |
|  |  - Sidecar        |                 |  - Rollback Service       | |
|  |    lifecycle       |                 |  - RunStore (SQLite)      | |
|  |  - Auto-updater   |                 |                           | |
|  +-------------------+                 +-------------+-------------+ |
|         |                                            |               |
+---------+--------------------------------------------+-----------+---+
          |                                            |           |
          v                                            v           v
+-------------------+                    +-------------------+  +--------+
|   OS Keychain     |                    |   Amazon S3       |  | SQLite |
|                   |                    |   Buckets         |  | runs.db|
|  AWS Credentials  |                    |                   |  |        |
+-------------------+                    +-------------------+  +--------+
```

---

## 2. Component Architecture

```
+------------------------------------------------------------------+
|                         FastAPI Backend                           |
|                                                                  |
|  +-------------------+     +-------------------+                 |
|  |   API Layer       |     |   Dependencies    |                 |
|  |                   |     |                   |                 |
|  |  /optimizer/scan  +---->+  scanner_service  +-----> boto3 S3  |
|  |  /optimizer/score +---->+  scoring_service  |                 |
|  |  /optimizer/exec  +---->+  execution_service+-----> boto3 S3  |
|  |  /optimizer/rollback+-->+  rollback_service +-----> boto3 S3  |
|  |  /optimizer/runs  +---->+  run_store        +-----> SQLite    |
|  |  /health          |     |                   |                 |
|  +-------------------+     +-------------------+                 |
|                                                                  |
|  +-------------------+     +-------------------+                 |
|  |   Models Layer    |     |   Core Layer      |                 |
|  |                   |     |                   |                 |
|  |  contracts.py     |     |  settings.py      |                 |
|  |  (Pydantic v2)    |     |  (env vars)       |                 |
|  |  7 enums          |     |                   |                 |
|  |  20+ models       |     |                   |                 |
|  +-------------------+     +-------------------+                 |
+------------------------------------------------------------------+
```

---

## 3. Data Flow: Scan → Score → Execute → Rollback

### 3.1 Scan Flow

```
User clicks "New Scan"
        |
        v
POST /optimizer/scan
  { include_buckets, exclude_buckets, max_objects_per_bucket }
        |
        v
ScannerService.scan()
        |
        +---> s3.list_buckets()          # Discover all buckets
        +---> For each bucket:
        |       +---> s3.list_objects_v2() # Paginate objects
        |       |       +---> Age >= 365d? --> DELETE_STALE_OBJECT (HIGH)
        |       |       +---> Age >= 90d && STANDARD? --> CHANGE_STORAGE_CLASS (MEDIUM)
        |       +---> s3.get_bucket_lifecycle_configuration()
        |       |       +---> NoSuchLifecycle? --> ADD_LIFECYCLE_POLICY (LOW)
        |       +---> s3.list_multipart_uploads()
        |               +---> Age >= 7d? --> DELETE_INCOMPLETE_UPLOAD (LOW)
        |
        v
RunStore.create(recommendations)
        |
        +---> INSERT INTO runs (status='scanned', recommendations_json=...)
        |
        v
Return ScanResponse { run_id, recommendations[], estimated_monthly_savings }
```

### 3.2 Score Flow

```
User clicks "Score"
        |
        v
POST /optimizer/score { run_id }
        |
        v
RunStore.get(run_id)  --> Load recommendations
        |
        v
ScoringService.score(recommendations)
        |
        +---> For each recommendation:
        |       |
        |       +---> _calculate_factor_scores()
        |       |       +---> reversibility:     REVERSIBILITY_SCORES[type]
        |       |       +---> data_loss_risk:    _data_loss_risk(type)
        |       |       +---> age_confidence:    _age_confidence(last_modified)
        |       |       +---> size_impact:       _size_impact(size_bytes)
        |       |       +---> access_confidence: _access_confidence(reason)
        |       |
        |       +---> _calculate_weighted_risk()
        |       |       risk = (100-rev)*0.30 + loss*0.25 + (100-age)*0.20
        |       |             + size*0.15 + (100-access)*0.10
        |       |
        |       +---> Approval logic:
        |       |       requires_approval = risk>=55 OR DELETE OR size>=10GB
        |       |       safe_to_automate  = risk<30 AND confidence>=70 AND !DELETE
        |       |
        |       +---> _calculate_savings()
        |               +---> Storage pricing matrix lookup
        |               +---> Transition cost calculation
        |               +---> Break-even analysis
        |
        +---> _aggregate_savings() --> SavingsSummary
        |
        v
RunStore.set_scores(run_id, scores, savings, summary)
        |
        +---> UPDATE runs SET status='scored', scores_json=...
        |
        v
Return ScoreResponse { scores[], savings_details[], savings_summary }
```

### 3.3 Execute Flow

```
User selects mode + clicks "Execute"
        |
        v
POST /optimizer/execute { run_id, mode, dry_run, max_actions }
        |
        v
RunStore.get(run_id)  --> Load recommendations + scores
        |
        v
ExecutionService.execute()
        |
        +---> _resolve_mode() --> (effective_mode, is_dry_run)
        +---> _granted_permissions() --> Set[str] from env
        |
        +---> For each recommendation (up to max_actions):
        |       |
        |       +---> Check: score exists?         --> No: FAILED
        |       +---> Check: mode eligible?        --> No: SKIPPED
        |       +---> Check: destructive guard?    --> Blocked: BLOCKED
        |       +---> Check: permissions?          --> Missing: BLOCKED
        |       +---> Check: dry_run?              --> Yes: DRY_RUN (simulate)
        |       |
        |       +---> _capture_pre_change_state()
        |       +---> _execute_action()
        |       |       +---> CHANGE_STORAGE_CLASS: s3.copy_object(StorageClass=...)
        |       |       +---> ADD_LIFECYCLE_POLICY: s3.put_bucket_lifecycle_configuration()
        |       |       +---> DELETE_INCOMPLETE:    s3.abort_multipart_upload()
        |       |       +---> DELETE_STALE:         s3.delete_object()
        |       +---> _capture_post_change_state()
        |       |
        |       +---> Build ExecutionActionResult
        |               +---> rollback_available = EXECUTED && reversible && !simulated
        |               +---> rollback_status = PENDING or NOT_APPLICABLE
        |
        v
RunStore.set_execution(run_id, execution)
        |
        +---> UPDATE runs SET status='executed', execution_json=...
        +---> INSERT INTO execution_audit (one row per action)
        |
        v
Return ExecuteResponse { eligible, executed, skipped, blocked, failed, action_results[] }
```

### 3.4 Rollback Flow

```
User clicks "Rollback" (or selects audit records)
        |
        v
POST /optimizer/rollback { run_id, execution_id, audit_ids, dry_run }
        |
        v
RunStore.list_execution_audit(run_id, execution_id, audit_ids)
        |
        v
RollbackService.rollback(audit_records)
        |
        +---> For each audit record:
        |       |
        |       +---> _rollback_eligible()?
        |       |       +---> rollback_available == True?
        |       |       +---> action_status == EXECUTED?
        |       |       +---> type in REVERSIBLE_ACTIONS?
        |       |       +---> No to any: SKIPPED
        |       |
        |       +---> dry_run?  --> Yes: DRY_RUN (no mutation)
        |       |
        |       +---> _rollback_action()
        |               +---> CHANGE_STORAGE_CLASS:
        |               |       s3.copy_object(StorageClass=original_class)
        |               +---> ADD_LIFECYCLE_POLICY:
        |                       original rules exist?
        |                         Yes: s3.put_bucket_lifecycle_configuration(original)
        |                         No:  s3.delete_bucket_lifecycle()
        |
        +---> If not dry_run:
        |       RunStore.update_rollback_status(audit_id, ROLLED_BACK)
        |
        v
Return RollbackResponse { attempted, rolled_back, skipped, failed, results[] }
```

---

## 4. Desktop Application Architecture

### 4.1 Process Model

```
+-----------------------------------------------+
|              Operating System                  |
|                                                |
|  +-------------------+  +-------------------+  |
|  |   Tauri Process   |  |  Sidecar Process  |  |
|  |   (Rust + WebView)|  |  (Python/uvicorn) |  |
|  |                   |  |                   |  |
|  |  React SPA        |  |  FastAPI app      |  |
|  |  renders in       |  |  on :8000         |  |
|  |  system WebView   |  |                   |  |
|  |                   |  |  Frozen by        |  |
|  |  Tauri commands:  |  |  PyInstaller      |  |
|  |  - load_credentials|  |  into standalone  |  |
|  |  - save_credentials|  |  binary           |  |
|  |  - check_updates  |  |                   |  |
|  |  - install_update |  |                   |  |
|  +--------+----------+  +--------+----------+  |
|           |                      |              |
|    OS Keychain            AWS S3 + SQLite       |
+-----------------------------------------------+
```

### 4.2 Startup Sequence

```
App launches
    |
    v
Tauri setup hook fires
    |
    +---> Load credentials from OS keychain
    |
    +---> Credentials exist?
    |       |
    |       No ----> Show main window (redirects to /settings)
    |       |
    |       Yes ---> Spawn sidecar with AWS env vars
    |                   |
    |                   +---> Poll GET /health every 300ms
    |                   |       |
    |                   |       +---> 200 OK? --> Show main window
    |                   |       +---> Timeout (10s)? --> Show window + offline banner
    |
    v
React app mounts
    |
    +---> Start health check polling (every 10s)
    +---> Check for updates (5s delay, production only)
    +---> Load credentials --> No creds? Redirect to /settings
    +---> Render Dashboard
```

### 4.3 Credential Flow

```
User enters credentials in Settings
    |
    v
React calls invoke("save_credentials", { creds })
    |
    v
Rust handler:
    +---> Write to OS keychain (service: "aws-cost-optimizer")
    +---> Kill existing sidecar process
    +---> Spawn new sidecar with updated env vars
    +---> Poll /health until ready (15s timeout)
    +---> Return success to React
    |
    v
React navigates to Dashboard
```

---

## 5. Data Model

### 5.1 State Machine

```
                    Run Lifecycle
                    =============

    +----------+       +--------+       +----------+
    | SCANNED  |------>| SCORED |------>| EXECUTED |
    +----------+       +--------+       +----------+
         |                  |                |
    recommendations    + scores         + execution
    created            + savings          results
                       + summary        + audit records


              Audit Record Rollback Status
              ============================

    +----------------+
    | NOT_APPLICABLE |  (irreversible actions: DELETE_*)
    +----------------+

    +---------+       +-------------+
    | PENDING |------>| ROLLED_BACK |  (successful rollback)
    +---------+       +-------------+
         |
         +----------> +--------+
                      | FAILED |  (rollback error)
                      +--------+
```

### 5.2 Entity Relationships

```
+-------------------+          +------------------------+
|       runs        |          |    execution_audit     |
+-------------------+          +------------------------+
| PK  run_id        |---1:N-->| PK  audit_id           |
|     status        |         | FK  run_id              |
|     recs_json     |         |     execution_id        |
|     scores_json   |         |     recommendation_id   |
|     savings_json  |         |     action_status       |
|     summary_json  |         |     pre_change_state    |
|     exec_json     |         |     post_change_state   |
|     created_at    |         |     rollback_status     |
|     updated_at    |         |     rolled_back_at      |
+-------------------+         |     created_at          |
                              +------------------------+
```

---

## 6. Risk Scoring Model

### 6.1 Factor Weights

```
Risk Score (0-100)
==================

  Reversibility ████████████████████████████████  30%
  Data Loss     ██████████████████████████        25%
  Age Confidence████████████████████              20%
  Size Impact   ████████████████                  15%
  Access Conf.  ██████████                        10%

Formula:
  risk = (100 - reversibility) * 0.30
       + data_loss_risk        * 0.25
       + (100 - age_confidence) * 0.20
       + size_impact           * 0.15
       + (100 - access_confidence) * 0.10
```

### 6.2 Scoring by Recommendation Type

```
                    Reversibility   Data Loss   Typical Risk
                    ─────────────   ─────────   ────────────
CHANGE_STORAGE       90 (high)      5 (low)     ~21 (LOW)
ADD_LIFECYCLE        100 (full)     0 (none)    ~22 (LOW)
DELETE_MULTIPART     100 (full)     10 (low)    ~15 (LOW)
DELETE_STALE         0 (none)       100 (high)  ~76 (HIGH)
```

### 6.3 Decision Boundaries

```
Risk Score:     0         30         55         60        100
                |          |          |          |          |
                |   LOW    |  MEDIUM  |          |   HIGH   |
                |          |          |          |          |
                | safe to  |          | requires |          |
                | automate |          | approval |          |
                |<-------->|          |<-------->|<-------->|
```

---

## 7. Execution Safety Model

### 7.1 Mode Hierarchy

```
                Increasing risk acceptance -->

  +----------+    +------+    +----------+    +------+
  | dry_run  |--->| safe |--->| standard |--->| full |
  +----------+    +------+    +----------+    +------+
  |          |    |      |    |          |    |      |
  | All recs |    | safe |    | !approval|    | All  |
  | simulated|    | _to_ |    | _required|    |eligible
  | no writes|    | auto |    |          |    |      |
  +----------+    +------+    +----------+    +------+

  Guardrails applied at every level:
  ┌─────────────────────────────────────────┐
  │  Permission check (EXECUTOR_GRANTED)    │
  │  Destructive guard (ALLOW_DESTRUCTIVE)  │
  │  Max actions limit                      │
  │  Pre-change state capture               │
  └─────────────────────────────────────────┘
```

### 7.2 Action Decision Tree

```
For each recommendation:

  Has matching score?
    No  --> FAILED ("Missing risk score")
    Yes |
        v
  Mode eligible? (safe_to_automate / requires_approval checks)
    No  --> SKIPPED
    Yes |
        v
  Is DELETE_STALE_OBJECT && !ALLOW_DESTRUCTIVE?
    Yes --> BLOCKED
    No  |
        v
  Has all required permissions?
    No  --> BLOCKED (lists missing permissions)
    Yes |
        v
  Is dry_run?
    Yes --> DRY_RUN (simulate, capture state, no S3 mutation)
    No  |
        v
  Execute S3 action
    Error --> FAILED (S3 error code + message)
    OK    --> EXECUTED (capture post-state, mark rollback available if reversible)
```

---

## 8. CI/CD Pipeline Architecture

```
                    Push/PR to main or dev
                            |
              +-------------+-------------+
              |                           |
              v                           v
     +----------------+         +------------------+
     |   ci.yml       |         |  desktop.yml     |
     +----------------+         +------------------+
     |                |         |                  |
     | dependency-    |         | Build matrix:    |
     | hygiene        |         |  macOS aarch64   |
     |  - depcheck    |         |  macOS x86_64    |
     |  - deps-check  |         |  Windows x86_64  |
     |                |         |  Linux x86_64    |
     | test (matrix)  |         |                  |
     |  - Python 3.11 |         | Per platform:    |
     |  - Python 3.12 |         |  1. Rust setup   |
     |  - Python 3.13 |         |  2. PyInstaller  |
     |  - unit tests  |         |  3. Sidecar build|
     |  - integ tests |         |  4. npm ci       |
     |  - coverage    |         |  5. Tauri build  |
     |                |         |  6. Upload       |
     | build          |         |     artifacts    |
     |  - Docker build|         +------------------+
     |  - Smoke test  |
     +----------------+


                    Push tag v*.*.*
                            |
                            v
                   +------------------+
                   |  release.yml     |
                   +------------------+
                   |                  |
                   | build-release    |
                   |  - 4 platforms   |
                   |  - Sidecar smoke |
                   |  - Code signing  |
                   |  - Tauri build   |
                   |  - Updater frag  |
                   |                  |
                   | publish-release  |
                   |  - Merge updater |
                   |  - GitHub Release|
                   |  - Upload assets |
                   |                  |
                   | package-manifests|
                   |  - Homebrew cask |
                   |  - WinGet manif. |
                   +------------------+
```

---

## 9. Technology Stack Map

```
Layer           Technology          Purpose
─────           ──────────          ───────

Desktop Shell   Tauri v2 (Rust)     Window management, credential storage,
                                    sidecar lifecycle, auto-updates

Frontend        React 19            UI components and routing
                TypeScript 5        Type safety
                Vite 6              Build tooling and HMR
                React Router 7      Client-side navigation

Backend         FastAPI 0.128       REST API framework
                Pydantic 2.12       Data validation and serialization
                Uvicorn 0.40        ASGI server

AWS             Boto3 1.42          S3 operations (scan, execute, rollback)

Storage         SQLite 3            Run state, scores, audit trail
                OS Keychain         AWS credential storage

Bundling        PyInstaller         Freeze Python into standalone binary

Testing         pytest 8.3          Test runner
                pytest-cov 6.0      Coverage measurement
                moto 5.1            AWS service mocking
                httpx 0.28          HTTP client for TestClient

CI/CD           GitHub Actions      Testing, building, releasing
                Docker              Server containerization
```
