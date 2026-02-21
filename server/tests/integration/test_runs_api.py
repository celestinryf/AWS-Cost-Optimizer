"""Integration tests for GET /api/v1/optimizer/runs and related endpoints."""

import pytest


def _scan(client, buckets=None):
    payload = {}
    if buckets:
        payload["include_buckets"] = buckets
    return client.post("/api/v1/optimizer/scan", json=payload).json()["run_id"]


def _scan_and_score(client):
    run_id = _scan(client)
    client.post("/api/v1/optimizer/score", json={"run_id": run_id})
    return run_id


def _scan_score_execute(client):
    run_id = _scan_and_score(client)
    client.post("/api/v1/optimizer/execute", json={"run_id": run_id, "mode": "dry_run"})
    return run_id


@pytest.mark.integration
class TestListRuns:
    def test_empty_list_before_any_scan(self, client):
        resp = client.get("/api/v1/optimizer/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_scan_returns_summaries(self, client):
        _scan(client)
        runs = client.get("/api/v1/optimizer/runs").json()
        assert len(runs) == 1
        run = runs[0]
        assert "run_id" in run
        assert "status" in run
        assert "recommendation_count" in run
        assert "estimated_monthly_savings" in run
        assert "updated_at" in run

    def test_list_includes_multiple_runs(self, client):
        _scan(client)
        _scan(client)
        runs = client.get("/api/v1/optimizer/runs").json()
        assert len(runs) == 2

    def test_list_recommendation_count_is_correct(self, client):
        _scan(client, buckets=["bucket-a"])  # 2 recommendations
        runs = client.get("/api/v1/optimizer/runs").json()
        assert runs[0]["recommendation_count"] == 2


@pytest.mark.integration
class TestGetRun:
    def test_get_run_returns_200(self, client):
        run_id = _scan(client)
        resp = client.get(f"/api/v1/optimizer/runs/{run_id}")
        assert resp.status_code == 200

    def test_get_run_after_score_includes_scores(self, client):
        run_id = _scan_and_score(client)
        body = client.get(f"/api/v1/optimizer/runs/{run_id}").json()
        assert len(body["scores"]) > 0
        assert body["savings_summary"] is not None

    def test_get_run_after_execute_includes_audit_records(self, client):
        run_id = _scan_score_execute(client)
        body = client.get(f"/api/v1/optimizer/runs/{run_id}").json()
        assert len(body["audit_records"]) > 0

    def test_get_nonexistent_run_returns_404(self, client):
        resp = client.get("/api/v1/optimizer/runs/does-not-exist")
        assert resp.status_code == 404

    def test_get_run_status_transitions(self, client):
        run_id = _scan(client)
        assert client.get(f"/api/v1/optimizer/runs/{run_id}").json()["status"] == "scanned"

        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        assert client.get(f"/api/v1/optimizer/runs/{run_id}").json()["status"] == "scored"

        client.post("/api/v1/optimizer/execute", json={"run_id": run_id, "mode": "dry_run"})
        assert client.get(f"/api/v1/optimizer/runs/{run_id}").json()["status"] == "executed"


@pytest.mark.integration
class TestAuditEndpoint:
    def test_audit_empty_before_execution(self, client):
        run_id = _scan(client)
        audit = client.get(f"/api/v1/optimizer/runs/{run_id}/audit").json()
        assert audit == []

    def test_audit_populated_after_execute(self, client):
        run_id = _scan_score_execute(client)
        audit = client.get(f"/api/v1/optimizer/runs/{run_id}/audit").json()
        assert len(audit) > 0

    def test_audit_record_has_expected_fields(self, client):
        run_id = _scan_score_execute(client)
        record = client.get(f"/api/v1/optimizer/runs/{run_id}/audit").json()[0]
        assert "audit_id" in record
        assert "action_status" in record
        assert "pre_change_state" in record
        assert "rollback_available" in record
        assert "rollback_status" in record

    def test_audit_for_nonexistent_run_returns_404(self, client):
        resp = client.get("/api/v1/optimizer/runs/ghost/audit")
        assert resp.status_code == 404
