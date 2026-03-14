# Learnings, Tech Debt, and Known Issues
## AWS Cost Optimizer

---

## 1. Bug Reports and Defect Tracking

### BUG-001: Public Key Breaking Desktop Build
**Commit:** `63aff6f`
**Severity:** Build-breaking
**Symptom:** Desktop CI build failed because the Tauri updater plugin required a valid minisign public key in `tauri.conf.json`, but the key was either missing or malformed.
**Root Cause:** The updater configuration included a public key that was either a placeholder or incorrectly formatted. Tauri v2 validates the key at build time, not at runtime.
**Fix:** Replaced the public key with a valid minisign public key generated for the project.
**Lesson:** Tauri v2's updater is strict about key format validation at build time. Always generate real keys even for development builds if the updater plugin is enabled.

### BUG-002: Environment Variable Keys for GitHub Actions
**Commit:** `2a3da59`
**Severity:** CI-breaking
**Symptom:** GitHub Actions workflows failed because environment variable names didn't match what the build scripts expected.
**Root Cause:** Mismatch between variable names in the workflow YAML and the scripts they invoked.
**Fix:** Corrected env var key names in the workflow configuration.
**Lesson:** CI environment variables are a common source of silent failures. Add explicit validation steps (e.g., "echo $VAR_NAME" assertions) early in the pipeline.

### BUG-003: Updater Signing Requirement in Desktop CI
**Commit:** `a16b2c5`
**Severity:** CI-breaking
**Symptom:** Desktop CI build failed because the updater plugin required signing artifacts, but CI builds for PRs don't have access to signing secrets.
**Root Cause:** Tauri's build process generates updater artifacts that need to be signed. In CI, signing secrets are only available on main/release branches, not on PR builds.
**Fix:** Bypass the updater signing requirement in CI builds by conditionally disabling updater artifact generation for non-release builds.
**Lesson:** Separate "build for testing" from "build for release" in CI. PR builds should validate that the code compiles and the app runs, not that signing works.

---

## 2. Root Cause Analyses

### RCA-001: SQLite `:memory:` Database Not Working in Tests
**Symptom:** Tests using `RunStore(db_path=":memory:")` lost data between operations.
**Investigation:** The RunStore opens a new `sqlite3.Connection` for each operation (for thread safety). SQLite's `:memory:` mode creates a separate database per connection — data written by one connection is invisible to the next.
**Root Cause:** Architectural mismatch between the "new connection per operation" pattern and `:memory:` semantics.
**Resolution:** Changed test fixture to use `tmp_path / "runs.db"` (temp file), ensuring all connections read/write the same database.
**Lesson:** SQLite `:memory:` is only useful when the same connection is reused. For services that open new connections, use a temp file.

### RCA-002: Dual Import Binding in Test Fixtures
**Symptom:** Integration tests were using real (non-mocked) service instances despite monkeypatching `app.dependencies`.
**Investigation:** Python's import system creates independent bindings. When `app.api.routes.optimizer` imports `from app.dependencies import scanner_service`, it creates a local reference. Patching `app.dependencies.scanner_service` doesn't affect the route module's existing reference.
**Root Cause:** Python module-level import binding. The route module holds its own copy of the reference, independent of the original module.
**Resolution:** Patched both `app.dependencies.scanner_service` AND `app.api.routes.optimizer.scanner_service` in the test fixture.
**Lesson:** When monkeypatching in Python, you must patch the name where it's used, not where it's defined. If a module imports a name at the top level, you need to patch both sites.

### RCA-003: Tauri Sidecar Not Starting on macOS
**Symptom:** The desktop app showed "Backend offline" on macOS after building, even though the sidecar binary was present.
**Investigation:** macOS Gatekeeper quarantines unsigned binaries downloaded from the internet or built without proper signing. The PyInstaller binary was being quarantined.
**Root Cause:** Missing ad-hoc code signature on the sidecar binary.
**Resolution:** Added ad-hoc signing (`codesign --force --sign -`) as a fallback when Apple Developer certificates aren't available. The release pipeline attempts real signing first and falls back to ad-hoc.
**Lesson:** macOS requires code signing for binaries to execute without quarantine. Even ad-hoc signing is sufficient for local development.

---

## 3. Known Issues

### KNOWN-001: Synchronous S3 Scanning Blocks the Server
**Severity:** Medium
**Description:** The scanner service makes synchronous boto3 calls. During a long scan (large bucket, many objects), the single Uvicorn worker is blocked and cannot respond to other requests, including health checks.
**Impact:** The frontend health check polling may show "Backend offline" during a scan. Other API calls will queue behind the scan.
**Workaround:** Use `max_objects_per_bucket` to limit scan size. Avoid scanning very large buckets (100K+ objects) without setting a reasonable limit.
**Proper Fix:** Migrate to aioboto3 for async S3 operations, or run the scan in a background thread/process.

### KNOWN-002: No Real Access Pattern Data
**Severity:** Low
**Description:** The scoring model's `access_confidence` factor is the weakest signal. It infers access patterns from the recommendation reason text (looking for keywords like "cold", "infrequent", "stale") and whether a `last_modified` date exists. It does not query S3 access logs, CloudWatch metrics, or S3 Storage Lens.
**Impact:** Objects that appear cold based on `last_modified` but are actually read frequently may receive higher-than-appropriate savings estimates.
**Workaround:** Review recommendations manually before executing, especially for `change_storage_class` recommendations. Use `dry_run` mode first.
**Proper Fix:** Integrate with S3 Storage Lens or CloudWatch S3 metrics for actual access frequency data.

### KNOWN-003: Permission Check is Not IAM Policy Evaluation
**Severity:** Low
**Description:** The executor checks permissions against the `EXECUTOR_GRANTED_PERMISSIONS` environment variable — a simple string comparison. It does not evaluate actual IAM policies, resource policies, SCPs, or VPC endpoint policies.
**Impact:** A user might configure permissions in the env var that don't match their actual IAM permissions, leading to S3 API errors during execution. Conversely, they might have the right IAM permissions but miss configuring the env var.
**Workaround:** Ensure `EXECUTOR_GRANTED_PERMISSIONS` matches the user's actual IAM permissions. Use `dry_run` mode to validate before real execution.
**Proper Fix:** Use `sts:GetCallerIdentity` + `iam:SimulatePrincipalPolicy` to validate actual permissions at runtime.

### KNOWN-004: Manual TypeScript/Python Type Sync
**Severity:** Low
**Description:** TypeScript interfaces in `client/src/types.ts` are manually maintained to mirror Python Pydantic models in `server/app/models/contracts.py`. Changes to the Python models require manual updates to the TypeScript types.
**Impact:** A field added to a Pydantic model but not to the TypeScript interface will be silently ignored by the frontend. A field removed from Pydantic but still referenced in TypeScript will cause a compile error (which is actually good).
**Workaround:** Review both files when making model changes.
**Proper Fix:** Auto-generate TypeScript types from FastAPI's OpenAPI spec using `openapi-typescript` or similar tooling.

### KNOWN-005: No Scan Progress Feedback
**Severity:** Low
**Description:** The scan endpoint is a synchronous POST that blocks until all buckets are scanned. The frontend shows a loading spinner but has no visibility into progress (which bucket is being scanned, how many objects processed, etc.).
**Impact:** Users scanning many buckets may think the app is frozen.
**Workaround:** Scan with `include_buckets` to limit scope.
**Proper Fix:** WebSocket connection for real-time progress updates, or a polling-based job status endpoint.

---

## 4. Tech Debt Log

### DEBT-001: Scoring Weights Are Heuristic
**Priority:** Medium
**Description:** The risk scoring weights (reversibility: 30, data_loss: 25, age_confidence: 20, size_impact: 15, access_confidence: 10) are based on engineering judgment, not empirical data.
**Why It's Debt:** Without production usage data, we can't validate whether these weights produce optimal outcomes (i.e., recommendations that users execute vs skip).
**Resolution Path:** Track user behavior (which recommendations are executed vs skipped) and use that data to tune weights. Consider A/B testing different weight configurations.

### DEBT-002: No Database Migrations
**Priority:** Medium
**Description:** Schema changes require dropping and recreating the database. There's no migration framework (like Alembic) to evolve the schema.
**Why It's Debt:** Adding a column to `runs` or `execution_audit` requires users to lose their existing data or manually alter the database.
**Resolution Path:** Add Alembic for schema migrations. Initial migration should capture the current schema as the baseline.

### DEBT-003: Single Storage Pricing Region
**Priority:** Low
**Description:** The storage pricing matrix uses a single set of prices (us-east-1). S3 pricing varies by region.
**Why It's Debt:** Savings estimates may be inaccurate for buckets in other regions.
**Resolution Path:** Look up the bucket's region via `get_bucket_location()` and use region-specific pricing.

### DEBT-004: No Request Rate Limiting
**Priority:** Low
**Description:** The API has no rate limiting. A frontend bug or misbehaving client could flood the server with requests.
**Why It's Debt:** Not a problem for a single-user desktop app, but would be critical for a web deployment.
**Resolution Path:** Add rate limiting middleware (e.g., `slowapi`) if the project moves to a web deployment.

### DEBT-005: Hardcoded Scanner Thresholds
**Priority:** Low
**Description:** Scanner thresholds are hardcoded constants: `_COLD_DAYS = 90`, `_STALE_DAYS = 365`, `_MULTIPART_DAYS = 7`, `_TARGET_CLASS = "GLACIER_IR"`.
**Why It's Debt:** Users may have different definitions of "cold" or "stale" for their workloads.
**Resolution Path:** Make thresholds configurable via environment variables or a configuration endpoint. Add UI controls in the scan modal.

### DEBT-006: No Pagination on List Endpoints
**Priority:** Low
**Description:** `GET /optimizer/runs` returns all runs without pagination. `GET /optimizer/runs/{id}/audit` returns all audit records.
**Why It's Debt:** With hundreds of runs or thousands of audit records, response payloads could become large.
**Resolution Path:** Add `?offset=0&limit=50` query parameters with cursor-based pagination.

---

## 5. Development Learnings

### Learning 1: Tauri v2 Sidecar Lifecycle Management
The sidecar process needs careful lifecycle management. Key discoveries:
- The sidecar must be killed when the app exits (Tauri handles this for spawned children)
- Saving new credentials requires killing the old sidecar and spawning a new one (you can't change env vars on a running process)
- Health check polling needs a timeout to avoid blocking the window from appearing
- The sidecar binary name must include the Rust target triple for Tauri to find it (e.g., `aws-cost-optimizer-api-x86_64-pc-windows-msvc.exe`)

### Learning 2: Moto Fixture Design
The `autouse=True` pattern for moto fixtures means every test runs in a mocked AWS context. Key design decisions:
- Create the mock bucket in the fixture, not in individual tests (DRY)
- Pre-populate with known objects so scanner tests have consistent input
- The fixture yields the S3 client so tests can add more objects if needed
- Clear the settings LRU cache around each test so env var patches take effect

### Learning 3: Pydantic v2 Serialization Modes
Pydantic v2's `model_dump(mode="json")` converts datetime to ISO strings, enums to their values, and nested models recursively. This is critical for SQLite storage:
- Use `mode="json"` when serializing for storage
- Use `model_validate()` for deserialization (handles type coercion)
- `model_dump()` without `mode="json"` keeps Python types (datetime objects, enum instances), which `json.dumps()` can't serialize directly

### Learning 4: PyInstaller Cross-Platform Gotchas
- macOS: Binary needs code signing (even ad-hoc) to avoid Gatekeeper quarantine
- Windows: Need to specify `.exe` suffix in the binary name
- Linux: Need to ensure the binary has execute permissions after copy
- All platforms: The `.spec` file should exclude unnecessary modules to reduce binary size
- The sidecar binary must be placed in `client/src-tauri/binaries/` with the exact naming convention Tauri expects

### Learning 5: GitHub Actions Release Pipeline Complexity
Building a multi-platform release pipeline with code signing revealed several complexities:
- Signing secrets are only available on protected branches, not PRs
- macOS signing requires a temporary keychain, certificate import, and identity verification
- Windows signing requires PFX import and thumbprint extraction
- Fallback to unsigned builds is essential for development and PR testing
- The updater manifest (`latest.json`) must be assembled from all platform builds
- Artifact paths differ between platforms (DMG vs MSI vs DEB locations)
