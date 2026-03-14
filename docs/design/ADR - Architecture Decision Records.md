# Architecture Decision Records (ADR)
## AWS Cost Optimizer

---

## ADR-001: Desktop App with Sidecar Backend

**Status:** Accepted
**Date:** 2025-02

### Context
We needed to deliver a user-facing tool for S3 cost optimization. Options considered:
1. **Web application** with hosted backend
2. **CLI tool**
3. **Desktop application** with embedded backend

### Decision
Desktop application (Tauri v2) with a PyInstaller-frozen Python backend spawned as a sidecar subprocess.

### Rationale
- **Security:** AWS credentials never leave the user's machine. No cloud-hosted backend means no credential transmission, no server-side breach risk, and no need for IAM role delegation.
- **Portability:** Single installer, no Docker/Python/pip prerequisites for the end user.
- **Offline-capable:** Works in air-gapped environments (S3 access only).

### Consequences
- (+) Zero infrastructure cost for the developer
- (+) Credentials stay local — strongest security posture
- (-) Larger bundle size (~50 MB for frozen Python runtime)
- (-) 5-10 second startup latency for the sidecar
- (-) Platform-specific builds required (macOS, Windows, Linux)
- (-) Harder to scale to multi-user — would require re-architecture

### Alternatives Rejected
- **Hosted web app:** Introduces credential management complexity (OAuth, IAM roles, secrets management). Adds hosting costs. Overkill for a single-user tool.
- **CLI tool:** Lower barrier to entry, but poor discoverability. Users can't easily browse recommendations, compare risk scores, or selectively rollback without a visual interface.

---

## ADR-002: Tauri v2 over Electron

**Status:** Accepted
**Date:** 2025-02

### Context
Desktop framework selection for the UI shell.

### Decision
Tauri v2 with system WebView.

### Rationale
- **Binary size:** ~5 MB shell vs Electron's ~150 MB (Chromium bundle).
- **Memory:** System WebView uses existing browser engine, no dedicated Chromium process.
- **Security model:** Tauri's capability-based permissions and strict CSP enforcement.
- **Rust backend:** Native performance for subprocess management, credential storage, and update checks.

### Consequences
- (+) Significantly smaller installer
- (+) Lower memory footprint
- (-) WebView rendering differences across OS versions (Safari on macOS, WebView2 on Windows, WebKitGTK on Linux)
- (-) Smaller ecosystem and community compared to Electron
- (-) Tauri v2 is relatively new — fewer examples and libraries

---

## ADR-003: SQLite over PostgreSQL

**Status:** Accepted
**Date:** 2025-02

### Context
Persistent storage for run state, scores, execution results, and audit trails.

### Decision
SQLite with file-based storage at `data/runs.db`.

### Rationale
- **Zero deployment complexity:** No external database service to provision or manage.
- **Embedded:** Ships inside the sidecar binary, works immediately.
- **Sufficient for workload:** Single user, single writer, read-heavy after writes.
- **Portable:** Database file can be backed up by copying a single file.

### Consequences
- (+) No database setup for users
- (+) Atomic transactions, crash-safe
- (-) Single-writer limitation — must use `--workers 1` in Uvicorn
- (-) No concurrent multi-user support
- (-) Thread-safe locking adds complexity in the `RunStore`

### Migration Path
The `RunStore` class abstracts all database operations. To migrate to PostgreSQL:
1. Replace `sqlite3` connections with `asyncpg` or `psycopg2`
2. Update SQL syntax (minor differences)
3. Remove thread locking (PostgreSQL handles concurrency)
4. Update Uvicorn to use multiple workers

---

## ADR-004: Weighted Risk Scoring Model

**Status:** Accepted
**Date:** 2025-02

### Context
Recommendations need to be ranked by risk to guide execution decisions. Simple classification (high/medium/low) loses nuance.

### Decision
Five-factor weighted scoring model:

| Factor | Weight | Measures |
|--------|--------|----------|
| Reversibility | 30% | Can the action be undone? |
| Data Loss Risk | 25% | Could data be permanently lost? |
| Age Confidence | 20% | How reliable is the age signal? |
| Size Impact | 15% | How much data is affected? |
| Access Confidence | 10% | How strong is the access pattern signal? |

### Rationale
- Reversibility is weighted highest because reversible actions are inherently safer regardless of other factors.
- Data loss risk is second because permanent data loss is the worst outcome.
- Age confidence matters because recommendations based on unreliable age data should be treated cautiously.
- Size impact reflects blast radius — a mistake on 100 GB hurts more than on 100 KB.
- Access confidence is lowest because S3 doesn't expose detailed access logs via standard APIs.

### Consequences
- (+) Transparent — factor scores visible in UI and API
- (+) Tunable — weights can be adjusted without changing the model structure
- (+) Enables clear automation boundaries (safe_to_automate vs requires_approval)
- (-) Weights are heuristic, not empirically derived from production data
- (-) More complex to explain to users than a simple classification

### Approval Logic (Derived from Scores)
- **Requires approval:** risk >= 55, OR DELETE_STALE_OBJECT, OR size >= 10 GB
- **Safe to automate:** risk < 30, AND confidence >= 70, AND not a deletion

---

## ADR-005: Progressive Execution Modes

**Status:** Accepted
**Date:** 2025-02

### Context
Users need to control how aggressively the system applies recommendations.

### Decision
Four execution modes with increasing risk acceptance:

| Mode | Executes | Description |
|------|----------|-------------|
| `dry_run` | Nothing | Validate eligibility, simulate results |
| `safe` | Low-risk, reversible, automated | Only `safe_to_automate=True` actions |
| `standard` | Non-approval-required | Excludes high-risk and approval-gated actions |
| `full` | Everything eligible | All actions that pass permission checks |

### Rationale
- Users can start with `dry_run` to preview, then escalate to `safe` for automatic wins, then `standard` for medium-risk, and `full` only when they've reviewed all flags.
- Each mode strictly includes the previous one (safe ⊂ standard ⊂ full).

### Consequences
- (+) Gradual trust-building with the system
- (+) `dry_run` is the default — safe by default
- (-) Four modes means four code paths to test and document
- (-) Users may be confused about which mode to use

---

## ADR-006: Pre-Change State Capture for Rollback

**Status:** Accepted
**Date:** 2025-02

### Context
Executed actions need to be reversible. Rollback requires knowing what the state was before the change.

### Decision
Capture a complete pre-change state snapshot before every mutation, stored in the audit record.

### Captured State per Action Type

| Action | Pre-Change State Captured |
|--------|---------------------------|
| CHANGE_STORAGE_CLASS | bucket, key, original storage_class, size_bytes, last_modified |
| ADD_LIFECYCLE_POLICY | bucket, existing lifecycle rules (or null if none existed) |
| DELETE_INCOMPLETE_UPLOAD | bucket, key, upload_id |
| DELETE_STALE_OBJECT | bucket, key, storage_class, size_bytes |

### Rollback Behavior

| Action | Rollback | How |
|--------|----------|-----|
| CHANGE_STORAGE_CLASS | Reversible | `CopyObject` back to original storage class |
| ADD_LIFECYCLE_POLICY | Reversible | Restore original rules or `DeleteBucketLifecycle` if none existed |
| DELETE_INCOMPLETE_UPLOAD | Not reversible | Upload data is gone |
| DELETE_STALE_OBJECT | Not reversible | Object data is gone |

### Consequences
- (+) Reliable rollback — original state is preserved, not guessed
- (+) Audit trail captures what changed and what it was before
- (-) Additional S3 API calls to read state before writing
- (-) Larger audit records (JSON blobs for lifecycle rules)

---

## ADR-007: OS Keychain for Credential Storage

**Status:** Accepted
**Date:** 2025-02

### Context
The desktop app needs AWS credentials (access key, secret key, region, optional session token).

### Decision
Store credentials in the OS-native keychain using the Rust `keyring` crate.

### Rationale
- macOS Keychain, Windows Credential Manager, and Linux Secret Service are all encrypted at rest.
- No plaintext credential files on disk.
- The OS handles encryption key management (tied to user login).

### Consequences
- (+) Strongest credential security posture for a desktop app
- (+) No custom encryption code to maintain
- (-) Platform-specific behavior — testing requires platform-specific CI
- (-) Linux requires `libsecret` or equivalent installed
- (-) Legacy migration path needed for users who had credentials in `credentials.json`

---

## ADR-008: Moto for AWS Mocking in Tests

**Status:** Accepted
**Date:** 2025-02

### Context
Tests must not make real AWS API calls. Need a mocking strategy for boto3.

### Decision
Use `moto` library with `@mock_aws` decorator, applied as an autouse fixture.

### Rationale
- Moto intercepts at the HTTP layer — all boto3 clients see a realistic mock S3.
- No need to manually mock individual method calls.
- Test data (buckets, objects, uploads) can be created with real boto3 calls.

### Consequences
- (+) Tests look like production code — same boto3 calls
- (+) No brittle mock.patch chains
- (-) Moto doesn't perfectly replicate all S3 behaviors (eventual consistency, rate limits)
- (-) Adding a new AWS service requires moto support for it

---

## ADR-009: Single Uvicorn Worker

**Status:** Accepted
**Date:** 2025-02

### Context
SQLite uses file-level locking. Multiple Uvicorn workers would each hold their own connection and contend for the lock.

### Decision
Run Uvicorn with `--workers 1`.

### Rationale
- SQLite's WAL mode allows concurrent reads but only one writer. With multiple workers, write contention causes `SQLITE_BUSY` errors.
- For a single-user desktop app, one worker is sufficient.

### Consequences
- (+) No write contention
- (+) Thread-safe locking in `RunStore` is sufficient
- (-) Cannot scale horizontally without replacing SQLite
- (-) A slow S3 scan blocks the worker (no async S3 calls currently)

### Future Path
If the app evolves to a multi-user web service:
1. Replace SQLite with PostgreSQL
2. Use async database driver (asyncpg)
3. Scale to multiple Uvicorn workers with a load balancer

---

## ADR-010: GitHub Releases for Auto-Updates

**Status:** Accepted
**Date:** 2025-02

### Context
Desktop users need a way to receive updates without manually downloading installers.

### Decision
Tauri's built-in updater plugin with GitHub Releases as the update source. Releases contain a `latest.json` manifest with download URLs and signatures.

### Rationale
- No custom update server infrastructure needed.
- GitHub Releases is free, reliable, and has CDN distribution.
- Tauri's updater handles signature verification (minisign), download, and in-place update.

### Consequences
- (+) Zero-cost update distribution
- (+) Cryptographic signature verification prevents tampering
- (-) Requires GitHub connectivity (no updates in air-gapped environments)
- (-) Release process must generate and upload `latest.json` with correct signatures
