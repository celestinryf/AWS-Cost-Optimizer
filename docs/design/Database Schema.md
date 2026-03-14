# Database Schema
## AWS Cost Optimizer

**Engine:** SQLite 3
**Location:** `data/runs.db` (configurable via `RUNS_DB_PATH`)
**Access Pattern:** Single-writer, read-heavy, thread-safe with Python `threading.Lock`

---

## Tables

### `runs`

Stores the complete state of each optimization run through its lifecycle (scanned → scored → executed).

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    status              TEXT NOT NULL,          -- 'scanned' | 'scored' | 'executed'
    recommendations_json TEXT NOT NULL,         -- JSON array of Recommendation objects
    scores_json         TEXT NOT NULL,          -- JSON array of RiskScore objects (empty until scored)
    savings_details_json TEXT NOT NULL,         -- JSON array of SavingsEstimate objects
    savings_summary_json TEXT,                  -- JSON SavingsSummary object (nullable until scored)
    execution_json      TEXT,                   -- JSON ExecuteResponse object (nullable until executed)
    created_at          TEXT NOT NULL,          -- ISO 8601 UTC timestamp
    updated_at          TEXT NOT NULL           -- ISO 8601 UTC timestamp
);

CREATE INDEX IF NOT EXISTS idx_runs_updated
    ON runs (updated_at DESC);
```

**Notes:**
- `recommendations_json`, `scores_json`, `savings_details_json` are serialized via `model_dump(mode="json")` and deserialized via `model_validate()`.
- `scores_json` starts as `"[]"` after scan, populated on score.
- `execution_json` starts as `NULL`, populated on execute.
- `updated_at` is refreshed on every state transition.

---

### `execution_audit`

Stores one record per action from every execution. Provides a complete audit trail with pre/post state for rollback.

```sql
CREATE TABLE IF NOT EXISTS execution_audit (
    audit_id                TEXT PRIMARY KEY,
    execution_id            TEXT NOT NULL,
    run_id                  TEXT NOT NULL,
    recommendation_id       TEXT NOT NULL,
    recommendation_type     TEXT NOT NULL,       -- enum value
    bucket                  TEXT NOT NULL,
    key                     TEXT,                 -- nullable (lifecycle policies have no key)
    action_status           TEXT NOT NULL,        -- 'dry_run' | 'executed' | 'skipped' | 'blocked' | 'failed'
    message                 TEXT NOT NULL,
    risk_level              TEXT NOT NULL,        -- 'low' | 'medium' | 'high'
    requires_approval       INTEGER NOT NULL,     -- 0 or 1
    permitted               INTEGER NOT NULL,     -- 0 or 1
    required_permissions_json TEXT NOT NULL,      -- JSON array of permission strings
    missing_permissions_json TEXT NOT NULL,       -- JSON array of permission strings
    simulated               INTEGER NOT NULL,     -- 0 or 1
    pre_change_state_json   TEXT NOT NULL,        -- JSON object
    post_change_state_json  TEXT,                 -- JSON object (nullable for blocked/failed)
    rollback_available      INTEGER NOT NULL,     -- 0 or 1
    rollback_status         TEXT NOT NULL,        -- 'pending' | 'not_applicable' | 'rolled_back' | 'failed'
    rolled_back_at          TEXT,                 -- ISO 8601 UTC (nullable, set on rollback)
    created_at              TEXT NOT NULL,        -- ISO 8601 UTC
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_run
    ON execution_audit (run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_execution
    ON execution_audit (execution_id);
```

**Notes:**
- Boolean fields stored as `INTEGER` (SQLite has no native bool type). 0 = false, 1 = true.
- `rollback_status` transitions: `not_applicable` (irreversible actions), `pending` (eligible for rollback), `rolled_back` (successfully reversed), `failed` (rollback error).
- `rolled_back_at` is set only when `rollback_status` transitions to `rolled_back`.
- Foreign key on `run_id` ensures referential integrity.

---

## Entity Relationship Diagram

```
+-------------------+          +------------------------+
|       runs        |          |    execution_audit     |
+-------------------+          +------------------------+
| PK  run_id        |----+     | PK  audit_id           |
|     status        |    |     |     execution_id        |
|     recs_json     |    +---->| FK  run_id              |
|     scores_json   |          |     recommendation_id   |
|     savings_json  |          |     recommendation_type |
|     summary_json  |          |     bucket              |
|     exec_json     |          |     key                 |
|     created_at    |          |     action_status       |
|     updated_at    |          |     message             |
+-------------------+          |     risk_level          |
                               |     requires_approval   |
                               |     permitted           |
                               |     required_perms_json |
                               |     missing_perms_json  |
                               |     simulated           |
                               |     pre_state_json      |
                               |     post_state_json     |
                               |     rollback_available  |
                               |     rollback_status     |
                               |     rolled_back_at      |
                               |     created_at          |
                               +------------------------+
```

**Cardinality:** One `run` has zero to many `execution_audit` records (created when execution occurs).

---

## State Transitions

### Run Status

```
  [scan]         [score]        [execute]
    |               |               |
    v               v               v
 SCANNED -------> SCORED -------> EXECUTED
```

- `SCANNED`: Run created with recommendations. scores_json = `[]`, execution_json = `NULL`.
- `SCORED`: Risk scores and savings estimates calculated. scores_json populated.
- `EXECUTED`: Actions applied (or dry-run simulated). execution_json populated, audit records inserted.

### Rollback Status (per audit record)

```
                    +---> ROLLED_BACK
                    |
 NOT_APPLICABLE     |  [rollback]
       or           |
    PENDING --------+
                    |
                    +---> FAILED
```

---

## RunStore API

The `RunStore` class (`app/state/store.py`) provides the data access layer:

| Method | Description | SQL |
|--------|-------------|-----|
| `create(recommendations)` | Insert new run (SCANNED) | INSERT INTO runs |
| `get(run_id)` | Fetch single run | SELECT * FROM runs WHERE run_id=? |
| `list()` | Fetch all runs (newest first) | SELECT * FROM runs ORDER BY updated_at DESC |
| `set_scores(run_id, scores, savings, summary)` | Update to SCORED | UPDATE runs SET status='scored', ... |
| `set_execution(run_id, execution)` | Update to EXECUTED + insert audit | UPDATE runs + INSERT INTO execution_audit |
| `list_execution_audit(run_id, execution_id?, audit_ids?)` | Query audit records | SELECT * FROM execution_audit WHERE ... |
| `update_rollback_status(audit_id, status, message?)` | Update rollback state | UPDATE execution_audit SET rollback_status=... |

**Thread Safety:** All methods acquire a `threading.Lock` before database operations. Each method opens and closes its own connection (no connection pooling).

**JSON Serialization:**
- Pydantic models → JSON: `json.dumps([m.model_dump(mode="json") for m in models])`
- JSON → Pydantic models: `[ModelClass.model_validate(item) for item in json.loads(payload)]`
