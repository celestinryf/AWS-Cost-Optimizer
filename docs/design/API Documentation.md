# API Documentation
## AWS Cost Optimizer

**Base URL:** `http://127.0.0.1:8000/api/v1`
**Content-Type:** `application/json`
**Error Format:** `{"detail": "<message>"}`

---

## Endpoints Overview

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| GET | `/health` | Health check | 200 |
| POST | `/optimizer/scan` | Scan S3 buckets for recommendations | 201 |
| POST | `/optimizer/score` | Score recommendations with risk/savings analysis | 200 |
| POST | `/optimizer/execute` | Execute (or dry-run) scored actions | 200 |
| POST | `/optimizer/rollback` | Roll back eligible executed actions | 200 |
| GET | `/optimizer/runs` | List all run summaries | 200 |
| GET | `/optimizer/runs/{run_id}` | Get full run details | 200 |
| GET | `/optimizer/runs/{run_id}/audit` | Get execution audit trail | 200 |

---

## Health Check

### `GET /api/v1/health`

Returns service health and environment info.

**Response 200:**
```json
{
  "status": "ok",
  "app": "aws-cost-optimizer-api",
  "environment": "development",
  "timestamp": "2026-03-05T12:00:00Z"
}
```

---

## Scan

### `POST /api/v1/optimizer/scan`

Scans S3 buckets and generates optimization recommendations. Creates a new run.

**Request Body:**
```json
{
  "include_buckets": ["my-bucket-1", "my-bucket-2"],
  "exclude_buckets": ["skip-this-bucket"],
  "max_objects_per_bucket": 1000
}
```

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `include_buckets` | string[] | `[]` | — | Buckets to scan. Empty = scan all accessible buckets. |
| `exclude_buckets` | string[] | `[]` | — | Buckets to skip. |
| `max_objects_per_bucket` | int | `1000` | 1–100,000 | Maximum objects to inspect per bucket. |

**Response 201:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "scanned",
  "recommendations": [
    {
      "id": "rec-001",
      "bucket": "my-bucket",
      "key": "archive/old-data.parquet",
      "recommendation_type": "change_storage_class",
      "risk_level": "medium",
      "reason": "Object in STANDARD storage, not modified in 120 days",
      "recommended_action": "Transition to GLACIER_IR",
      "estimated_monthly_savings": 1.52,
      "size_bytes": 83886080,
      "storage_class": "STANDARD",
      "last_modified": "2025-11-05T10:00:00Z"
    }
  ],
  "estimated_monthly_savings": 1.52,
  "scanned_at": "2026-03-05T12:01:00Z"
}
```

**Recommendation Types:**

| Type | Risk Level | Description |
|------|-----------|-------------|
| `change_storage_class` | MEDIUM | Object in STANDARD, not accessed in 90+ days |
| `add_lifecycle_policy` | LOW | Bucket has no lifecycle policy configured |
| `delete_incomplete_upload` | LOW | Multipart upload incomplete for 7+ days |
| `delete_stale_object` | HIGH | Object not modified in 365+ days |

---

## Score

### `POST /api/v1/optimizer/score`

Applies the risk scoring model and savings calculator to a scanned run.

**Request Body:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response 200:**
```json
{
  "run_id": "550e8400-...",
  "status": "scored",
  "scores": [
    {
      "recommendation_id": "rec-001",
      "risk_score": 34,
      "confidence_score": 68,
      "impact_score": 40,
      "risk_level": "medium",
      "requires_approval": false,
      "safe_to_automate": false,
      "execution_recommendation": "Review before executing",
      "factors": ["Reversible action (storage class change)", "Low data loss risk"],
      "factor_scores": {
        "reversibility": 90,
        "data_loss_risk": 5,
        "age_confidence": 65,
        "size_impact": 60,
        "access_confidence": 50
      }
    }
  ],
  "savings_details": [
    {
      "recommendation_id": "rec-001",
      "current_monthly_cost": 1.84,
      "projected_monthly_cost": 0.32,
      "monthly_savings": 1.52,
      "transition_cost": 0.00002,
      "minimum_duration_risk": 0.32,
      "net_first_month": 1.52,
      "net_annual_savings": 18.24,
      "break_even_days": 0,
      "estimate_confidence": "high",
      "assumptions": ["Based on current S3 pricing"]
    }
  ],
  "savings_summary": {
    "total_monthly_savings": 1.52,
    "total_annual_savings": 18.24,
    "total_transition_costs": 0.00002,
    "net_first_month": 1.52,
    "high_confidence_count": 1,
    "medium_confidence_count": 0,
    "low_confidence_count": 0
  },
  "safe_to_automate": 0,
  "requires_approval": 0,
  "scored_at": "2026-03-05T12:02:00Z"
}
```

**Error Responses:**
- `404`: Run ID not found
- `422`: Missing `run_id` field

### Risk Score Calculation

```
weighted_risk = (100 - reversibility) * 0.30
              + data_loss_risk        * 0.25
              + (100 - age_confidence) * 0.20
              + size_impact           * 0.15
              + (100 - access_confidence) * 0.10
```

| Risk Score | Level |
|-----------|-------|
| 0–29 | LOW |
| 30–59 | MEDIUM |
| 60–100 | HIGH |

### Storage Pricing Matrix ($/GB/month)

| Storage Class | Price |
|---------------|-------|
| STANDARD | $0.023 |
| INTELLIGENT_TIERING | $0.023 |
| STANDARD_IA | $0.0125 |
| ONEZONE_IA | $0.01 |
| GLACIER_IR | $0.004 |
| GLACIER | $0.0036 |
| DEEP_ARCHIVE | $0.00099 |

---

## Execute

### `POST /api/v1/optimizer/execute`

Executes scored recommendations in the specified mode.

**Request Body:**
```json
{
  "run_id": "550e8400-...",
  "mode": "dry_run",
  "dry_run": null,
  "max_actions": 100
}
```

| Field | Type | Default | Constraints | Description |
|-------|------|---------|-------------|-------------|
| `run_id` | string | required | — | Run to execute |
| `mode` | enum | `"dry_run"` | dry_run, safe, standard, full | Execution mode |
| `dry_run` | bool? | `null` | — | Override: `true` forces dry-run regardless of mode |
| `max_actions` | int | `100` | 1–10,000 | Maximum actions to execute |

**Execution Modes:**

| Mode | Eligible Actions | Description |
|------|------------------|-------------|
| `dry_run` | All | Simulate only, no mutations |
| `safe` | `safe_to_automate=True` | Low-risk, reversible, high-confidence |
| `standard` | `requires_approval=False` | Low + medium risk, excludes approval-gated |
| `full` | All eligible | Everything that passes permission checks |

**Response 200:**
```json
{
  "execution_id": "exec-550e...",
  "run_id": "550e8400-...",
  "status": "executed",
  "mode": "dry_run",
  "dry_run": true,
  "eligible": 5,
  "executed": 0,
  "skipped": 0,
  "blocked": 0,
  "failed": 0,
  "action_results": [
    {
      "audit_id": "aud-001",
      "recommendation_id": "rec-001",
      "recommendation_type": "change_storage_class",
      "bucket": "my-bucket",
      "key": "archive/old-data.parquet",
      "risk_level": "medium",
      "requires_approval": false,
      "status": "dry_run",
      "message": "Dry-run: would transition archive/old-data.parquet to GLACIER_IR",
      "permitted": true,
      "required_permissions": ["s3:GetObject", "s3:PutObject"],
      "missing_permissions": [],
      "simulated": true,
      "pre_change_state": {
        "bucket": "my-bucket",
        "key": "archive/old-data.parquet",
        "storage_class": "STANDARD",
        "size_bytes": 83886080,
        "last_modified": "2025-11-05T10:00:00Z",
        "risk_level": "medium"
      },
      "post_change_state": {
        "action": "change_storage_class",
        "target": "Transition to GLACIER_IR",
        "simulated": true
      },
      "rollback_available": false,
      "rollback_status": "not_applicable"
    }
  ],
  "executed_at": "2026-03-05T12:03:00Z"
}
```

**Action Statuses:**

| Status | Meaning |
|--------|---------|
| `dry_run` | Simulated, no mutation |
| `executed` | Successfully applied |
| `skipped` | Not eligible for this mode, or over max_actions |
| `blocked` | Missing permissions or destructive guard |
| `failed` | S3 API error or missing score |

**Error Responses:**
- `404`: Run ID not found
- `409`: Run has not been scored yet
- `422`: Invalid mode or max_actions out of range

### Required Permissions per Action

| Recommendation Type | Required Permissions |
|--------------------|---------------------|
| `change_storage_class` | `s3:GetObject`, `s3:PutObject` |
| `add_lifecycle_policy` | `s3:GetLifecycleConfiguration`, `s3:PutLifecycleConfiguration` |
| `delete_incomplete_upload` | `s3:ListBucketMultipartUploads`, `s3:AbortMultipartUpload` |
| `delete_stale_object` | `s3:GetObject`, `s3:DeleteObject` |

### Destructive Action Guard

`DELETE_STALE_OBJECT` actions are blocked by default. To enable:
- Set environment variable `ALLOW_DESTRUCTIVE_EXECUTION=true`
- Ensure `s3:DeleteObject` is in `EXECUTOR_GRANTED_PERMISSIONS`

---

## Rollback

### `POST /api/v1/optimizer/rollback`

Reverses eligible executed actions.

**Request Body:**
```json
{
  "run_id": "550e8400-...",
  "execution_id": null,
  "audit_ids": [],
  "dry_run": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `run_id` | string | required | Run to rollback |
| `execution_id` | string? | `null` | Specific execution batch. Defaults to latest. |
| `audit_ids` | string[] | `[]` | Specific audit records to rollback. Empty = all eligible. |
| `dry_run` | bool | `true` | Preview rollback without applying. |

**Rollback Eligibility:**
- `rollback_available` must be `true`
- `action_status` must be `executed`
- Recommendation type must be reversible (`change_storage_class` or `add_lifecycle_policy`)

**Response 200:**
```json
{
  "run_id": "550e8400-...",
  "execution_id": "exec-550e...",
  "dry_run": false,
  "attempted": 3,
  "rolled_back": 2,
  "skipped": 1,
  "failed": 0,
  "results": [
    {
      "audit_id": "aud-001",
      "recommendation_id": "rec-001",
      "recommendation_type": "change_storage_class",
      "status": "rolled_back",
      "message": "Restored archive/old-data.parquet to STANDARD.",
      "rolled_back": true
    }
  ],
  "processed_at": "2026-03-05T12:04:00Z"
}
```

**Rollback Action Statuses:**

| Status | Meaning |
|--------|---------|
| `dry_run` | Would rollback, but in dry-run mode |
| `rolled_back` | Successfully reversed |
| `skipped` | Not eligible (irreversible or not executed) |
| `failed` | S3 API error during rollback |

---

## List Runs

### `GET /api/v1/optimizer/runs`

Returns summaries of all runs, ordered by most recently updated.

**Response 200:**
```json
[
  {
    "run_id": "550e8400-...",
    "status": "scored",
    "recommendation_count": 12,
    "estimated_monthly_savings": 15.42,
    "updated_at": "2026-03-05T12:02:00Z"
  }
]
```

---

## Get Run Details

### `GET /api/v1/optimizer/runs/{run_id}`

Returns full run details including all phases.

**Response 200:** Returns `RunDetails` object with recommendations, scores, savings_details, savings_summary, execution, audit_records, created_at, updated_at.

**Error Response:**
- `404`: Run ID not found

---

## Get Audit Trail

### `GET /api/v1/optimizer/runs/{run_id}/audit`

Returns execution audit records for a run.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `execution_id` | string | No | Filter by specific execution batch |

**Response 200:** Returns list of `ExecutionAuditRecord` objects.

**Error Response:**
- `404`: Run ID not found

---

## Data Contracts

### Enums

| Enum | Values |
|------|--------|
| `RunStatus` | `scanned`, `scored`, `executed` |
| `RecommendationType` | `change_storage_class`, `add_lifecycle_policy`, `delete_incomplete_upload`, `delete_stale_object` |
| `RiskLevel` | `low`, `medium`, `high` |
| `ExecutionMode` | `dry_run`, `safe`, `standard`, `full` |
| `ExecutionActionStatus` | `dry_run`, `executed`, `skipped`, `blocked`, `failed` |
| `RollbackStatus` | `pending`, `not_applicable`, `rolled_back`, `failed` |
| `RollbackActionStatus` | `dry_run`, `rolled_back`, `skipped`, `failed` |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `aws-cost-optimizer-api` | Application name in health response |
| `ENVIRONMENT` | `development` | Environment label |
| `API_PREFIX` | `/api/v1` | API route prefix |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed origins |
| `RUNS_DB_PATH` | `data/runs.db` | SQLite database file path |
| `EXECUTOR_GRANTED_PERMISSIONS` | S3 read/write permissions | Comma-separated IAM actions |
| `ALLOW_DESTRUCTIVE_EXECUTION` | `false` | Enable DELETE_STALE_OBJECT execution |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region for S3 client |
