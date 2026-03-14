# Interview Prep
## AWS Cost Optimizer

---

## "Walk Me Through This Project"

AWS Cost Optimizer is a full-stack desktop application I built to help engineers reduce their S3 storage costs. The core problem is that S3 objects accumulate over time in expensive storage classes — data that was hot a year ago is now cold, but nobody moves it because auditing buckets manually doesn't scale.

The application follows a four-phase workflow: **scan, score, execute, and rollback**.

**Scan** connects to a user's AWS account and inspects their S3 buckets. It identifies four types of optimization opportunities: objects sitting in STANDARD storage that haven't been touched in 90+ days (could be in Glacier), buckets without any lifecycle policies, incomplete multipart uploads wasting space, and objects older than a year that might be candidates for deletion.

**Score** takes those recommendations and runs them through a weighted risk model I designed. Five factors — reversibility, data loss risk, age confidence, size impact, and access confidence — are combined with specific weights to produce a 0-100 risk score. It also calculates projected savings using AWS's storage pricing matrix, including transition costs and break-even analysis. The scoring engine determines whether each action is safe to automate or requires human approval.

**Execute** applies the changes in progressive safety modes. You start with a dry-run to see what would happen. Then `safe` mode only touches low-risk, reversible, high-confidence actions. `standard` adds medium-risk. `full` does everything that passes permission checks. Before every mutation, the system captures the pre-change state — the original storage class, existing lifecycle rules — so it can rollback.

**Rollback** uses that captured state to reverse changes. Storage class transitions are rolled back by copying the object back to its original class. Lifecycle policies are rolled back by restoring the original rules, or removing them entirely if none existed before.

On the architecture side, the backend is a Python FastAPI server using SQLite for persistence and boto3 for AWS operations. The frontend is a React/TypeScript SPA. I packaged everything as a Tauri v2 desktop application — the Python backend gets frozen by PyInstaller into a standalone binary that Tauri spawns as a sidecar process. AWS credentials are stored in the OS keychain (macOS Keychain, Windows Credential Manager). The whole thing installs as a single DMG, MSI, or AppImage.

The CI/CD pipeline runs tests across Python 3.11-3.13, builds Docker images with smoke tests, and produces cross-platform desktop installers for macOS, Windows, and Linux. There are 245+ tests with 80%+ coverage enforced.

---

## Technical Deep-Dive Questions

### Q: Why did you choose a desktop app instead of a web app?

**A:** Security was the primary driver. AWS credentials — specifically IAM access keys — are extremely sensitive. In a web app architecture, those credentials would need to travel from the user's browser to my server, which means I'd need to handle credential encryption in transit, secure storage on the server side, and the user would have to trust my infrastructure. With a desktop app, the credentials never leave the user's machine. They go from the Settings page directly into the OS keychain, and when the sidecar backend needs them, they're injected as environment variables in the subprocess — all local.

The secondary benefit is zero infrastructure cost. There's no server to host, no database to provision, no scaling to worry about. The SQLite database lives in the application's data directory on the user's machine.

The tradeoff is distribution complexity. I need to build and sign installers for three platforms, handle auto-updates, and deal with WebView rendering differences. But for a tool where security is paramount and the user count is small, that tradeoff is worth it.

### Q: Walk me through your risk scoring algorithm. How did you arrive at those weights?

**A:** The scoring model uses five weighted factors:

- **Reversibility (30%)** — This is weighted highest because it's the single most important safety property. If I can undo an action, the downside is bounded. A storage class change can be reversed with a CopyObject call. A deleted object cannot be recovered.
- **Data Loss Risk (25%)** — Second highest because permanent data loss is the worst outcome. DELETE_STALE_OBJECT gets a data_loss_risk of 100. CHANGE_STORAGE_CLASS gets 5 (data is preserved, just moved).
- **Age Confidence (20%)** — The strength of our signal. If an object was last modified 365 days ago, we're very confident it's cold. If it was modified 30 days ago, we're less sure.
- **Size Impact (15%)** — Blast radius. Making a mistake on a 100 GB file is worse than on a 100 KB file.
- **Access Confidence (10%)** — Lowest because S3 doesn't expose detailed access logs through standard APIs. We infer access patterns from the reason text (mentions of "cold" or "stale"), but it's a weak signal.

The weights are heuristic, not empirically derived. In a production system, I'd tune them based on user feedback — track which scored recommendations users actually execute vs skip, and use that as training data. But the architecture makes tuning easy: the weights are in a single dictionary, and the factor scores are all exposed in the API response so users can see exactly why something scored the way it did.

### Q: How does the execution pipeline handle failures and partial execution?

**A:** The execution pipeline processes recommendations sequentially, up to a configurable `max_actions` limit. For each action, it runs through a series of checks before attempting the mutation:

1. **Mode eligibility** — Is this action's risk profile appropriate for the selected mode? Safe mode only runs `safe_to_automate=True` actions.
2. **Destructive guard** — Is this a DELETE_STALE_OBJECT? If so, is `ALLOW_DESTRUCTIVE_EXECUTION` enabled?
3. **Permission check** — Does the configured permission set include all required IAM actions? CHANGE_STORAGE_CLASS needs `s3:GetObject` and `s3:PutObject`.
4. **Pre-state capture** — Record the current state before mutation.
5. **Execute** — Make the S3 API call.
6. **Post-state capture** — Record what changed.

If any check fails, the action gets an appropriate status (skipped, blocked, or failed) and the pipeline continues to the next recommendation. A failure on one action doesn't abort the batch. This is deliberate — in a batch of 50 actions, you don't want one permission error to cancel 49 successful ones.

Each action result includes the full context: what was attempted, what permissions were needed vs missing, the pre-change state, and whether rollback is available. This goes into the audit trail for compliance and debugging.

### Q: Why SQLite instead of PostgreSQL?

**A:** The workload profile is: single user, single writer, read-heavy after writes, small data volumes (kilobytes to low megabytes of JSON). SQLite handles this perfectly with zero deployment complexity — it ships embedded in the sidecar binary.

The main constraint is single-writer. SQLite uses file-level locking, so I run Uvicorn with `--workers 1` and use a Python `threading.Lock` in the RunStore for thread safety. This is fine for a desktop app where one person is running one scan at a time.

If the project evolved into a shared web service with concurrent users, I'd migrate to PostgreSQL. The RunStore class abstracts all database operations, so the migration would be straightforward: replace `sqlite3` with `psycopg2`, update a few SQL syntax differences, remove the thread lock, and increase the worker count.

### Q: How does the sidecar pattern work? What happens at startup?

**A:** When Tauri launches, the Rust setup hook checks if AWS credentials exist in the OS keychain. If they do, it spawns the PyInstaller-frozen Python binary as a child process, passing the credentials as environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, etc.).

Then it polls `http://127.0.0.1:8000/api/v1/health` every 300 milliseconds until the backend responds, with a 10-second timeout. Once the health check passes, it shows the main window. If the backend fails to start within the timeout, it shows the window anyway with an "offline" banner.

On the frontend side, the React app also polls `/health` every 10 seconds and shows a status indicator. When the user saves new credentials in Settings, the Rust backend kills the existing sidecar process, spawns a new one with the updated environment variables, and waits for it to come online — this time with a 15-second timeout since we're also writing to the keychain.

The tradeoff is startup latency. The frozen Python binary takes 5-10 seconds to start because PyInstaller has to extract and load the Python runtime. But for a tool that you launch, use for a few minutes, and close, that's acceptable.

### Q: How do you handle the type safety between Python and TypeScript?

**A:** The contracts are defined once in Python using Pydantic v2 models (`app/models/contracts.py`) and manually mirrored in TypeScript (`client/src/types.ts`). Both sides define the same enums, the same field names and types, and the same nested structures.

The synchronization is manual, which is a deliberate tradeoff. I could have used code generation (like openapi-typescript-codegen from FastAPI's OpenAPI spec), but the contract is stable enough that manual mirroring is simpler and gives me full control over the TypeScript types.

The Pydantic side provides runtime validation — if the frontend sends malformed JSON, FastAPI returns a 422 with specific validation errors. The TypeScript side provides compile-time safety — the API client (`client.ts`) has typed methods that enforce request shapes and cast response types.

Where this could break is if I update a Pydantic model and forget to update the TypeScript interface. The integration tests would catch missing fields (the TestClient validates against Pydantic), but they wouldn't catch a TypeScript-only consumer receiving unexpected data. A future improvement would be to auto-generate the TypeScript types from the OpenAPI spec as part of the build.

### Q: What tradeoffs did you make for testing?

**A:** I use moto for S3 mocking, which intercepts at the HTTP layer so all boto3 calls hit a simulated S3. This means tests use the same code as production — no mock.patch chains, no brittle assertion on internal method calls.

The tradeoff is that moto doesn't perfectly replicate S3 behavior. It doesn't simulate rate limiting, eventual consistency, or IAM policy evaluation. For example, my permission check is a simple set comparison against `EXECUTOR_GRANTED_PERMISSIONS`, not a real IAM policy evaluation. In production, a user might have the right permissions via a policy but the wrong ones via the environment variable configuration — that's a gap.

Another tradeoff: the `tmp_store` fixture uses a temp file instead of SQLite `:memory:`. This is because the RunStore opens a new connection per operation (for thread safety), and `:memory:` databases are per-connection — each new connection would see an empty database. Using a temp file ensures all connections see the same data, but it's slightly slower.

### Q: How would you scale this to support multiple AWS services?

**A:** The architecture is set up to extend naturally. Each service would get its own scanner module (`ec2/service.py`, `rds/service.py`, etc.) that produces `Recommendation` objects. The scoring service already works with the generic `Recommendation` model — I'd just need to add new entries to the REVERSIBILITY_SCORES and data_loss_risk mappings.

The execution service would need service-specific action handlers, but the guardrail framework (mode eligibility, permission checks, pre-state capture) would be reused. The RunStore and audit trail would work unchanged since they store JSON-serialized models.

The main complexity would be in the scoring — each AWS service has different risk profiles. Stopping an EC2 instance is fully reversible; deleting an EBS snapshot isn't. The five-factor model handles this, but the specific scores for each recommendation type would need careful calibration.

### Q: What would you do differently if you started over?

**A:** Three things:

1. **Async S3 operations.** The scanner currently makes synchronous boto3 calls, which blocks the single Uvicorn worker. If a scan takes 30 seconds, the health check endpoint is also blocked. I'd use aioboto3 for non-blocking S3 calls.

2. **Auto-generated TypeScript types.** The manual mirroring between Pydantic and TypeScript works but doesn't scale. I'd generate TypeScript interfaces from FastAPI's OpenAPI spec as a build step.

3. **WebSocket for scan progress.** Currently the frontend has no visibility into scan progress — it fires the request and waits. A WebSocket connection would let the backend push "scanning bucket 3 of 12" updates to the UI.

### Q: How do you handle security in this application?

**A:** Security is designed in layers:

1. **Credential isolation:** AWS credentials are stored in the OS-native keychain (encrypted at rest, tied to user login). They're never written to disk in plaintext and never leave the machine.

2. **CSP enforcement:** Tauri's Content Security Policy restricts the frontend to connecting only to `http://127.0.0.1:8000`. No external API calls are possible from the WebView.

3. **Execution guardrails:** Destructive actions (object deletion) are blocked by default. The `ALLOW_DESTRUCTIVE_EXECUTION` flag must be explicitly set to `true`. Even then, the user needs `s3:DeleteObject` in their granted permissions.

4. **Progressive modes:** The default execution mode is `dry_run` — no mutations at all. Users must explicitly escalate to `safe`, `standard`, or `full`.

5. **Pre-change state capture:** Every mutation is recorded with before/after state, enabling rollback and audit.

6. **Docker security:** The containerized backend runs as a non-root user (`app:app`).

7. **Update verification:** Desktop updates are signed with minisign and verified before installation.

---

## Behavioral and Design Questions

### Q: Tell me about a technical challenge you faced during this project.

**A:** The hardest part was getting the sidecar lifecycle right on all three platforms. On macOS, the PyInstaller binary needs to be ad-hoc signed or it gets quarantined by Gatekeeper. On Windows, the binary path needs the `.exe` suffix and the process management is different. On Linux, the binary needs to be executable and in the right location.

The startup timing was tricky too. The Python sidecar takes 5-10 seconds to start, and I needed the Tauri frontend to wait for it without showing a blank window. I implemented a health check polling loop with a 300ms interval and 10-second timeout, with the main window hidden until the backend responds.

The release pipeline was complex — building on three platforms, bundling the sidecar for each, generating updater manifests with signatures, and handling code signing (or graceful fallback when signing certificates aren't available). It took several iterations to get right.

### Q: How do you decide when something is "good enough" vs needs more work?

**A:** I apply a pragmatic threshold. For this project, the scoring weights are heuristic — they're reasonable defaults based on my understanding of S3 cost optimization, but they're not backed by production data. That's good enough for now because: (a) the weights are transparent and visible in every API response, (b) they're trivially tuneable (one dictionary change), and (c) the approval/automation boundaries add a safety layer even if the exact scores are slightly off.

On the other hand, I didn't cut corners on the audit trail or rollback system. If someone runs the executor in `full` mode and something goes wrong, they need to know exactly what changed and be able to reverse it. That part needed to be right, not "good enough."

### Q: How would you present this to a product manager or non-technical stakeholder?

**A:** "This tool saves money on S3 storage — automatically. You connect it to your AWS account, it scans your S3 buckets, tells you where you're wasting money (like keeping old data in expensive storage), ranks the recommendations by risk, and lets you apply the changes with a safety net. If something goes wrong, you can undo it with one click. It runs on your desktop and your AWS credentials never leave your computer."

Then I'd show the Dashboard → Scan → Score → Execute dry-run flow as a demo, highlighting the savings estimate and the risk scores.

### Q: What are the biggest risks or limitations of this system?

**A:**

1. **Access pattern blindness:** S3 doesn't expose detailed access logs through standard APIs. An object might look cold (not modified in 90 days) but be read frequently by other services. The scoring model accounts for this with the access_confidence factor (weighted at only 10%), but it's still the weakest signal.

2. **Transition cost underestimation:** The savings calculator uses list prices. It doesn't account for request costs (GET/PUT during transitions), S3 Select usage, or cross-region transfer costs.

3. **Single-user limitation:** SQLite and single-worker Uvicorn mean this is a one-person tool. Scaling to a team would require PostgreSQL and a proper web deployment.

4. **Synchronous scanning:** A scan of a large bucket (100K objects) blocks the server. Other endpoints (like health checks) are unresponsive during the scan.
