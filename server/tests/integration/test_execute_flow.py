"""Integration tests for POST /api/v1/optimizer/execute."""

import pytest


def _scan_and_score(client, buckets=None):
    payload = {}
    if buckets:
        payload["include_buckets"] = buckets
    run_id = client.post("/api/v1/optimizer/scan", json=payload).json()["run_id"]
    client.post("/api/v1/optimizer/score", json={"run_id": run_id})
    return run_id


@pytest.mark.integration
class TestExecuteEndpoint:
    def test_execute_dry_run_returns_200(self, client):
        run_id = _scan_and_score(client)
        resp = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run"},
        )
        assert resp.status_code == 200

    def test_execute_dry_run_response_has_dry_run_true(self, client):
        run_id = _scan_and_score(client)
        body = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run"},
        ).json()
        assert body["dry_run"] is True

    def test_execute_dry_run_all_actions_simulated(self, client):
        run_id = _scan_and_score(client)
        body = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run"},
        ).json()
        for action in body["action_results"]:
            assert action["simulated"] is True

    def test_execute_before_score_returns_409(self, client):
        run_id = client.post("/api/v1/optimizer/scan", json={}).json()["run_id"]
        resp = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run"},
        )
        assert resp.status_code == 409
        assert "score" in resp.json()["detail"].lower()

    def test_execute_nonexistent_run_returns_404(self, client):
        resp = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": "ghost", "mode": "dry_run"},
        )
        assert resp.status_code == 404

    def test_execute_creates_audit_records(self, client):
        run_id = _scan_and_score(client)
        client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run"},
        )
        audit = client.get(f"/api/v1/optimizer/runs/{run_id}/audit").json()
        assert len(audit) > 0

    def test_execute_updates_run_status_to_executed(self, client):
        run_id = _scan_and_score(client)
        client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run"},
        )
        run = client.get(f"/api/v1/optimizer/runs/{run_id}").json()
        assert run["status"] == "executed"

    def test_execute_full_mode_live_has_executed_actions(self, client, allow_destructive):
        run_id = _scan_and_score(client)
        body = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "full", "dry_run": False},
        ).json()
        assert body["dry_run"] is False
        assert body["executed"] > 0

    def test_execute_response_counts_are_consistent(self, client):
        run_id = _scan_and_score(client)
        body = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run"},
        ).json()
        total = body["executed"] + body["skipped"] + body["blocked"] + body["failed"]
        assert total == len(body["action_results"])

    def test_execute_invalid_mode_returns_422(self, client):
        run_id = _scan_and_score(client)
        resp = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "turbo"},
        )
        assert resp.status_code == 422

    def test_execute_max_actions_above_10000_returns_422(self, client):
        run_id = _scan_and_score(client)
        resp = client.post(
            "/api/v1/optimizer/execute",
            json={"run_id": run_id, "mode": "dry_run", "max_actions": 99999},
        )
        assert resp.status_code == 422
