"""Integration tests for state transitions across the full API pipeline.

Tests multi-step sequences that span scan → score → execute → rollback,
verifying idempotency, re-entrant calls, explicit execution_id routing,
and the audit_ids=[] vs audit_ids=None distinction.

Note: all enum values in API responses are lowercase (e.g. 'scanned', 'dry_run').
"""

import pytest

# All tests use the `client` fixture from conftest.py which provides a
# TestClient with a fresh SQLite store and all real services.


# ---------------------------------------------------------------------------
# Helpers: HTTP wrappers
# ---------------------------------------------------------------------------

def scan(client, buckets=None) -> dict:
    payload = {"include_buckets": buckets or ["test-bucket"]}
    r = client.post("/api/v1/optimizer/scan", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def score(client, run_id: str) -> dict:
    r = client.post("/api/v1/optimizer/score", json={"run_id": run_id})
    assert r.status_code == 200, r.text
    return r.json()


def execute(client, run_id: str, mode: str = "dry_run", dry_run: bool = True):
    """Returns the raw Response object so callers can check status_code."""
    r = client.post("/api/v1/optimizer/execute", json={
        "run_id": run_id,
        "mode": mode,
        "dry_run": dry_run,
        "max_actions": 100,
    })
    return r


def rollback(client, run_id: str, execution_id=None, audit_ids=None, dry_run=True):
    """Returns the raw Response object."""
    payload = {"run_id": run_id, "dry_run": dry_run}
    if execution_id is not None:
        payload["execution_id"] = execution_id
    if audit_ids is not None:
        payload["audit_ids"] = audit_ids
    return client.post("/api/v1/optimizer/rollback", json=payload)


def get_audit(client, run_id: str) -> list:
    r = client.get(f"/api/v1/optimizer/runs/{run_id}/audit")
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Execute without score → 409
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestExecuteWithoutScore:
    def test_execute_before_score_returns_409(self, client):
        scan_resp = scan(client)
        resp = execute(client, scan_resp["run_id"])
        assert resp.status_code == 409

    def test_execute_empty_scan_after_score_returns_409(self, client):
        """Scan with all buckets excluded → 0 recs → scores=[] (falsy) → execute returns 409.

        `include_buckets=[]` falls back to the default bucket list, so we must
        explicitly include AND exclude the same bucket to produce scan_targets=[].
        """
        r = client.post("/api/v1/optimizer/scan", json={
            "include_buckets": ["dummy-bucket"],
            "exclude_buckets": ["dummy-bucket"],
        })
        assert r.status_code == 201
        run_id = r.json()["run_id"]
        assert r.json()["recommendations"] == []

        score_resp = client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        assert score_resp.status_code == 200
        assert score_resp.json()["scores"] == []

        exec_resp = execute(client, run_id)
        assert exec_resp.status_code == 409


# ---------------------------------------------------------------------------
# Score twice → second overwrites first
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestScoreTwice:
    def test_score_twice_succeeds_both_times(self, client):
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        r1 = client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        r2 = client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_score_twice_run_status_stays_scored(self, client):
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        r = client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        assert r.json()["status"] == "scored"

    def test_score_after_execute_succeeds(self, client):
        """Score route has no state guard — calling it after execute is allowed."""
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        execute(client, run_id)
        # Score again — should succeed (no 409 from score route)
        r = client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Execute twice → both succeed (scores still present after first execute)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestExecuteTwice:
    def test_execute_twice_both_succeed(self, client):
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        r1 = execute(client, run_id)
        r2 = execute(client, run_id)
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_execute_twice_generates_distinct_execution_ids(self, client):
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        r1 = execute(client, run_id)
        r2 = execute(client, run_id)
        assert r1.json()["execution_id"] != r2.json()["execution_id"]

    def test_execute_twice_audit_records_accumulate(self, client):
        """Both execution batches are stored as separate audit records."""
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        r1 = execute(client, run_id)
        r2 = execute(client, run_id)
        audit = get_audit(client, run_id)
        exec_ids = {a["execution_id"] for a in audit}
        assert r1.json()["execution_id"] in exec_ids
        assert r2.json()["execution_id"] in exec_ids


# ---------------------------------------------------------------------------
# Rollback with explicit execution_id
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRollbackWithExplicitExecutionId:
    def test_rollback_with_explicit_execution_id_succeeds(self, client):
        """Providing execution_id explicitly routes rollback to that specific batch."""
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        exec_resp = execute(client, run_id)
        execution_id = exec_resp.json()["execution_id"]

        rb = rollback(client, run_id, execution_id=execution_id, dry_run=True)
        assert rb.status_code == 200

    def test_rollback_with_wrong_execution_id_returns_404(self, client):
        """Providing a nonexistent execution_id → no audit records → 404."""
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        execute(client, run_id)

        rb = rollback(client, run_id, execution_id="nonexistent-exec-id", dry_run=True)
        assert rb.status_code == 404

    def test_rollback_without_execution_and_no_execution_record_returns_409(self, client):
        """No execution_id provided + no execution record on the run → 409."""
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        # Do NOT call execute — no execution record exists
        rb = rollback(client, run_id, dry_run=True)
        assert rb.status_code == 409


# ---------------------------------------------------------------------------
# audit_ids=[] vs audit_ids=None in rollback route
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRollbackAuditIdsFilter:
    def test_audit_ids_empty_list_routes_to_all_records(self, client):
        """audit_ids=[] → route converts to None (via `or None`) → all records returned."""
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        exec_resp = execute(client, run_id)
        exec_data = exec_resp.json()

        # Rollback with audit_ids=[] should be same as audit_ids=None (all records)
        rb_empty = rollback(client, run_id, execution_id=exec_data["execution_id"],
                            audit_ids=[], dry_run=True)
        rb_none = rollback(client, run_id, execution_id=exec_data["execution_id"],
                           audit_ids=None, dry_run=True)

        assert rb_empty.status_code == 200
        assert rb_none.status_code == 200
        assert rb_empty.json()["attempted"] == rb_none.json()["attempted"]

    def test_audit_ids_none_omitted_routes_to_all_records(self, client):
        """audit_ids not in payload → defaults to None → all records."""
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        exec_resp = execute(client, run_id)
        execution_id = exec_resp.json()["execution_id"]

        # Post without audit_ids key at all
        r = client.post("/api/v1/optimizer/rollback", json={
            "run_id": run_id,
            "execution_id": execution_id,
            "dry_run": True,
        })
        assert r.status_code == 200
        assert isinstance(r.json()["attempted"], int)


# ---------------------------------------------------------------------------
# Error cases: unknown run_id
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestUnknownRunId:
    def test_score_unknown_run_returns_404(self, client):
        r = client.post("/api/v1/optimizer/score", json={"run_id": "does-not-exist"})
        assert r.status_code == 404

    def test_execute_unknown_run_returns_404(self, client):
        r = client.post("/api/v1/optimizer/execute", json={
            "run_id": "does-not-exist",
            "mode": "dry_run",
            "dry_run": True,
            "max_actions": 100,
        })
        assert r.status_code == 404

    def test_rollback_unknown_run_returns_404(self, client):
        r = rollback(client, "does-not-exist")
        assert r.status_code == 404

    def test_get_run_unknown_returns_404(self, client):
        r = client.get("/api/v1/optimizer/runs/does-not-exist")
        assert r.status_code == 404

    def test_get_audit_unknown_run_returns_404(self, client):
        r = client.get("/api/v1/optimizer/runs/does-not-exist/audit")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Full pipeline: scan → score → execute → rollback
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFullPipeline:
    def test_full_dry_run_pipeline(self, client):
        # Scan
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        assert scan_resp["status"] == "scanned"

        # Score
        score_resp = score(client, run_id)
        assert score_resp["status"] == "scored"

        # Execute (dry run)
        exec_resp = execute(client, run_id)
        assert exec_resp.status_code == 200
        exec_data = exec_resp.json()
        assert exec_data["run_id"] == run_id

        # Audit records should exist
        audit = get_audit(client, run_id)
        assert isinstance(audit, list)

        # Rollback dry run
        if audit:
            rb = rollback(client, run_id, execution_id=exec_data["execution_id"], dry_run=True)
            assert rb.status_code == 200
            assert rb.json()["dry_run"] is True

    def test_run_details_includes_audit_after_execute(self, client):
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        score(client, run_id)
        execute(client, run_id)

        r = client.get(f"/api/v1/optimizer/runs/{run_id}")
        assert r.status_code == 200
        data = r.json()
        assert "audit_records" in data
        assert isinstance(data["audit_records"], list)

    def test_run_status_is_executed_after_execute(self, client):
        scan_resp = scan(client)
        run_id = scan_resp["run_id"]
        score(client, run_id)
        execute(client, run_id)

        r = client.get(f"/api/v1/optimizer/runs/{run_id}")
        assert r.json()["status"] == "executed"
