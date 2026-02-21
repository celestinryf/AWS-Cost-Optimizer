"""Integration tests for health endpoint and complete workflow."""

import pytest


@pytest.mark.integration
class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_health_response_status_is_ok(self, client):
        body = client.get("/api/v1/health").json()
        assert body["status"] == "ok"

    def test_health_response_has_required_fields(self, client):
        body = client.get("/api/v1/health").json()
        assert "app" in body
        assert "environment" in body
        assert "timestamp" in body


@pytest.mark.integration
class TestMalformedRequests:
    def test_scan_max_objects_below_1_returns_422(self, client):
        resp = client.post("/api/v1/optimizer/scan", json={"max_objects_per_bucket": 0})
        assert resp.status_code == 422

    def test_score_missing_run_id_returns_422(self, client):
        resp = client.post("/api/v1/optimizer/score", json={})
        assert resp.status_code == 422

    def test_execute_invalid_mode_returns_422(self, client):
        resp = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": "x", "mode": "turbo"},
        )
        assert resp.status_code == 422

    def test_execute_max_actions_above_10000_returns_422(self, client):
        resp = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": "x", "mode": "dry_run", "max_actions": 99999},
        )
        assert resp.status_code == 422


@pytest.mark.integration
class TestCompleteWorkflow:
    def test_full_happy_path_scan_score_execute_audit_rollback(self, client):
        """End-to-end workflow: scan → score → execute (dry_run) → audit → rollback (dry_run)."""

        # 1. Scan
        scan_resp = client.post(
            "/api/v1/optimizer/scan",
            json={"include_buckets": ["test-bucket"]},
        )
        assert scan_resp.status_code == 201
        run_id = scan_resp.json()["run_id"]
        assert len(scan_resp.json()["recommendations"]) == 2

        # 2. Score
        score_resp = client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        assert score_resp.status_code == 200
        score_body = score_resp.json()
        assert score_body["status"] == "scored"
        assert len(score_body["scores"]) == 2
        assert score_body["savings_summary"]["total_monthly_savings"] > 0

        # 3. Execute (dry_run)
        exec_resp = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run"},
        )
        assert exec_resp.status_code == 200
        exec_body = exec_resp.json()
        assert exec_body["dry_run"] is True
        assert len(exec_body["action_results"]) == 2

        # 4. Get run details
        run_resp = client.get(f"/api/v1/optimizer/runs/{run_id}")
        assert run_resp.status_code == 200
        run_body = run_resp.json()
        assert run_body["status"] == "executed"
        assert len(run_body["scores"]) == 2
        assert len(run_body["audit_records"]) == 2

        # 5. Get audit trail
        audit = client.get(f"/api/v1/optimizer/runs/{run_id}/audit").json()
        assert len(audit) == 2
        for record in audit:
            assert record["action_status"] == "dry_run"

        # 6. Rollback (dry_run) — all actions are simulated so none are rollback_available
        rollback_resp = client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": run_id, "dry_run": True},
        )
        assert rollback_resp.status_code == 200
        rollback_body = rollback_resp.json()
        assert rollback_body["attempted"] == 2
        assert rollback_body["rolled_back"] + rollback_body["skipped"] + rollback_body["failed"] == 2

        # 7. Verify run appears in list
        runs = client.get("/api/v1/optimizer/runs").json()
        run_ids = [r["run_id"] for r in runs]
        assert run_id in run_ids
