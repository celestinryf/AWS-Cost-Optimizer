# Runbook / Operations Guide
## AWS Cost Optimizer

This guide covers deployment, monitoring, troubleshooting, and maintenance for operators and DevOps engineers.

---

## 1. Deployment Options

### Option A: Desktop Application (Recommended for Individual Use)

Download the installer from [GitHub Releases](https://github.com/celestinryf/AWS-Cost-Optimizer/releases):

| Platform | Installer | Notes |
|----------|-----------|-------|
| macOS (Apple Silicon) | `.dmg` | Requires macOS 10.13+ |
| macOS (Intel) | `.dmg` | Requires macOS 10.13+ |
| Windows | `.msi` or `.exe` (NSIS) | Requires Windows 10+ |
| Linux | `.deb` or `.AppImage` | Requires WebKitGTK 4.1 |

The desktop app bundles the Python backend as a sidecar — no Python, pip, or Docker needed.

### Option B: Docker (Recommended for Server/Shared Use)

```bash
cd server
cp .env.example .env
# Edit .env with your configuration
make docker-run
```

This runs `docker compose up --build`, which:
- Builds the Docker image from `server/Dockerfile`
- Starts the API on port 8000
- Mounts a persistent volume for the SQLite database
- Configures a health check on `/api/v1/health`

**Docker Compose Configuration:**
```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    volumes: ["db_data:/data"]
    env_file: .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped
```

### Option C: Direct Python (Development)

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

**Important:** Always use `--workers 1`. SQLite's file-level locking does not support multiple concurrent writers. Multiple workers will cause `SQLITE_BUSY` errors.

---

## 2. Configuration

### Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `APP_NAME` | `aws-cost-optimizer-api` | No | Application name in health response |
| `ENVIRONMENT` | `development` | No | Environment label (`development`, `production`) |
| `API_PREFIX` | `/api/v1` | No | API route prefix |
| `CORS_ORIGINS` | `http://localhost:3000,...` | No | Comma-separated allowed CORS origins |
| `RUNS_DB_PATH` | `data/runs.db` | No | SQLite database file path |
| `EXECUTOR_GRANTED_PERMISSIONS` | S3 read/write set | No | Comma-separated IAM action strings |
| `ALLOW_DESTRUCTIVE_EXECUTION` | `false` | No | Enable `DELETE_STALE_OBJECT` actions |
| `AWS_ACCESS_KEY_ID` | — | Yes | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | — | Yes | AWS secret key |
| `AWS_DEFAULT_REGION` | `us-east-1` | No | AWS region for S3 client |
| `AWS_SESSION_TOKEN` | — | No | Temporary session token (for assumed roles) |

### Production Checklist

- [ ] Set `ENVIRONMENT=production`
- [ ] Set `RUNS_DB_PATH` to an absolute path on a persistent volume
- [ ] Configure `CORS_ORIGINS` to match your frontend's origin
- [ ] Review `EXECUTOR_GRANTED_PERMISSIONS` — only grant what you need
- [ ] Keep `ALLOW_DESTRUCTIVE_EXECUTION=false` unless you explicitly need object deletion
- [ ] Ensure AWS credentials have least-privilege S3 permissions
- [ ] Use `--workers 1` for Uvicorn (SQLite constraint)

---

## 3. Monitoring

### Health Check

```bash
curl http://localhost:8000/api/v1/health
```

**Healthy response:**
```json
{
  "status": "ok",
  "app": "aws-cost-optimizer-api",
  "environment": "production",
  "timestamp": "2026-03-05T12:00:00Z"
}
```

**Monitoring integration:**
- Docker's built-in healthcheck polls this endpoint every 30 seconds
- The desktop app polls every 10 seconds and shows an offline banner if unreachable
- Integrate with external monitoring (UptimeRobot, Prometheus blackbox exporter) by targeting `GET /api/v1/health`

### Key Metrics to Watch

| Metric | How to Check | Concern Threshold |
|--------|-------------|-------------------|
| Health endpoint response | `curl /api/v1/health` | Non-200 or timeout > 5s |
| Database file size | `ls -lh data/runs.db` | > 100 MB (indicates many runs without cleanup) |
| Scan duration | Time between POST /scan request and response | > 60s (consider reducing `max_objects_per_bucket`) |
| Sidecar startup time | Time from app launch to health check pass | > 15s (PyInstaller extraction issue) |

### Logs

The backend does not write structured logs to file by default. Uvicorn logs go to stdout/stderr.

**Docker:** View logs with `docker compose logs -f api`

**Desktop:** Sidecar stdout/stderr is captured by Tauri but not surfaced in the UI. Check the Tauri console (dev tools) for backend output.

**Recommended logging improvement:** Add a logging middleware or configure Python's `logging` module to write JSON-structured logs to a file.

---

## 4. Database Management

### Location

| Deployment | Path |
|------------|------|
| Docker | `/data/runs.db` (mounted volume `db_data`) |
| Desktop (macOS) | `~/Library/Application Support/com.awscostoptimizer/data/runs.db` |
| Desktop (Windows) | `%APPDATA%\com.awscostoptimizer\data\runs.db` |
| Desktop (Linux) | `~/.config/com.awscostoptimizer/data/runs.db` |
| Direct Python | `./data/runs.db` (relative to server working directory) |

### Backup

SQLite databases can be backed up by copying the file while the application is stopped:

```bash
# Stop the application first, then:
cp data/runs.db data/runs.db.backup.$(date +%Y%m%d)
```

For hot backup (while running):

```bash
sqlite3 data/runs.db ".backup 'data/runs.db.backup'"
```

### Database Size Management

The database grows with each run. To check:

```bash
sqlite3 data/runs.db "SELECT COUNT(*) FROM runs;"
sqlite3 data/runs.db "SELECT COUNT(*) FROM execution_audit;"
```

To remove old runs (manual cleanup):

```bash
# Delete runs older than 90 days and their audit records
sqlite3 data/runs.db "
  DELETE FROM execution_audit WHERE run_id IN (
    SELECT run_id FROM runs WHERE updated_at < datetime('now', '-90 days')
  );
  DELETE FROM runs WHERE updated_at < datetime('now', '-90 days');
  VACUUM;
"
```

### Schema Inspection

```bash
sqlite3 data/runs.db ".schema"
sqlite3 data/runs.db ".tables"
```

---

## 5. Troubleshooting

### Backend Won't Start

**Symptom:** Health check returns connection refused or timeout.

| Cause | Fix |
|-------|-----|
| Port 8000 already in use | `lsof -i :8000` (macOS/Linux) or `netstat -ano | findstr 8000` (Windows). Kill the conflicting process. |
| Missing AWS credentials | Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in environment or `.env` file. |
| Corrupt database | Rename `data/runs.db` to force re-creation. Previous data will be lost. |
| Python version mismatch | Ensure Python 3.11+. Check with `python --version`. |

### Desktop App Shows "Backend Offline"

**Symptom:** The offline banner appears in the header.

| Cause | Fix |
|-------|-----|
| Sidecar still starting | Wait 10-15 seconds. The PyInstaller binary takes time to extract and start. |
| No credentials saved | Go to Settings and enter AWS credentials. The sidecar won't start without them. |
| Sidecar crashed | Restart the application. Check system logs for crash reports. |
| Port conflict | Another process is using port 8000. Close it and restart. |
| macOS Gatekeeper | Right-click the app → Open to bypass quarantine on first launch. |

### Scan Returns Empty Recommendations

| Cause | Fix |
|-------|-----|
| No accessible buckets | Check AWS credentials have `s3:ListAllMyBuckets` and `s3:ListBucket` permissions. |
| All buckets excluded | Review `exclude_buckets` in the scan request. |
| Objects are all recent | Objects must be 90+ days old for storage class recommendations, 365+ for deletion. |
| Objects already in Glacier | `CHANGE_STORAGE_CLASS` only applies to objects in `STANDARD`. |
| `max_objects_per_bucket` too low | Increase the limit to scan more objects. |

### Execution Actions Are Blocked

| Cause | Fix |
|-------|-----|
| Missing permissions | Add the required IAM actions to `EXECUTOR_GRANTED_PERMISSIONS`. See API docs for per-action requirements. |
| Destructive guard | Set `ALLOW_DESTRUCTIVE_EXECUTION=true` for `DELETE_STALE_OBJECT` actions. |
| Wrong execution mode | `safe` mode only runs `safe_to_automate=True` actions. Try `standard` or `full`. |
| Not scored yet | Execute returns 409 if the run hasn't been scored. Run score first. |

### Rollback Fails

| Cause | Fix |
|-------|-----|
| Action is irreversible | `DELETE_INCOMPLETE_UPLOAD` and `DELETE_STALE_OBJECT` cannot be rolled back. |
| Already rolled back | Check `rollback_status` in the audit trail — it may already be `rolled_back`. |
| S3 permission error | Rollback needs the same permissions as execution (e.g., `s3:PutObject` for storage class restore). |
| Object was modified externally | If someone changed the object after execution, rollback may overwrite their changes. |

### Database Locked Error

**Symptom:** `sqlite3.OperationalError: database is locked`

| Cause | Fix |
|-------|-----|
| Multiple Uvicorn workers | Ensure `--workers 1`. SQLite doesn't support concurrent writers from different processes. |
| Long-running scan blocking | The scan holds the GIL during synchronous S3 calls. Wait for it to complete. |
| External tool has the DB open | Close any SQLite browser or tool that has `runs.db` open. |

---

## 6. AWS IAM Policy

Minimum IAM policy for full functionality:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostOptimizerScan",
      "Effect": "Allow",
      "Action": [
        "s3:ListAllMyBuckets",
        "s3:ListBucket",
        "s3:GetBucketLifecycleConfiguration",
        "s3:ListBucketMultipartUploads"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CostOptimizerExecute",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:PutLifecycleConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:AbortMultipartUpload"
      ],
      "Resource": "arn:aws:s3:::*"
    }
  ]
}
```

**Read-only (scan only, no execution):**
Remove the `CostOptimizerExecute` statement. The scanner only needs the actions in `CostOptimizerScan`.

**With object deletion:**
Add `s3:DeleteObject` to the `CostOptimizerExecute` statement and set `ALLOW_DESTRUCTIVE_EXECUTION=true`.

---

## 7. Updating

### Desktop App

The app checks for updates automatically on launch (5-second delay). When a new version is available:
1. A banner appears with the new version number
2. Click "Install & Restart" to download and apply the update
3. The app restarts with the new version

Updates are signed with minisign and verified before installation.

### Docker

```bash
cd server
git pull
make docker-run  # Rebuilds and restarts
```

The SQLite database is on a persistent volume and survives container rebuilds.

### Direct Python

```bash
cd server
git pull
pip install -r requirements.txt
# Restart uvicorn
```

---

## 8. Disaster Recovery

### Data Loss

If the SQLite database is corrupted or deleted:
- The application creates a new empty database on startup
- All historical runs, scores, and audit trails are lost
- No data exists in AWS that could be used to reconstruct runs

**Prevention:** Back up `runs.db` regularly, especially before upgrades.

### Accidental Execution

If actions were executed that shouldn't have been:
1. Go to the Run Detail page or Audit Trail
2. Identify the affected actions
3. Use Rollback (dry-run first) to preview the reversal
4. Execute the rollback for eligible (reversible) actions
5. For irreversible actions (`DELETE_STALE_OBJECT`, `DELETE_INCOMPLETE_UPLOAD`), the data cannot be recovered through the application

**Prevention:** Always start with `dry_run` mode. Use `safe` mode for automated runs. Reserve `full` mode for reviewed, approved actions only.
