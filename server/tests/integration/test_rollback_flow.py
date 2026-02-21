"""Integration tests for POST /api/v1/optimizer/rollback."""

import pytest


def _scan_score_execute(client, live: bool = False):
    run_id = client.post("/api/v1/optimizer/scan", json={}).json()["run_id"]
    client.post("/api/v1/optimizer/score", json={"run_id": run_id})
    mode = "full" if live else "dry_run"
    client.post(
        "/api/v1/optimizer/execute",
        json={"run_id": run_id, "mode": mode, "dry_run": not live},
    )
    return run_id


@pytest.mark.integration
class TestRollbackEndpoint:
    def test_rollback_dry_run_after_dry_execute_returns_200(self, client):
        run_id = _scan_score_execute(client, live=False)
        resp = client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": run_id, "dry_run": True},
        )
        assert resp.status_code == 200

    def test_rollback_dry_run_does_not_change_audit_status(self, client):
        run_id = _scan_score_execute(client, live=False)
        client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": run_id, "dry_run": True},
        )
        audit = client.get(f"/api/v1/optimizer/runs/{run_id}/audit").json()
        for record in audit:
            assert record["rollback_status"] != "rolled_back"

    def test_rollback_live_updates_audit_rollback_status(self, client):
        # live execute so actions have rollback_available=True, then rollback
        run_id = _scan_score_execute(client, live=True)
        client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": run_id, "dry_run": False},
        )
        audit = client.get(f"/api/v1/optimizer/runs/{run_id}/audit").json()
        rolled_back = [r for r in audit if r["rollback_status"] == "rolled_back"]
        assert len(rolled_back) > 0

    def test_rollback_with_no_execution_returns_409(self, client):
        run_id = client.post("/api/v1/optimizer/scan", json={}).json()["run_id"]
        resp = client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": run_id, "dry_run": True},
        )
        assert resp.status_code == 409

    def test_rollback_nonexistent_run_returns_404(self, client):
        resp = client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": "ghost", "dry_run": True},
        )
        assert resp.status_code == 404

    def test_rollback_selective_via_audit_ids(self, client):
        run_id = _scan_score_execute(client, live=True)
        audit = client.get(f"/api/v1/optimizer/runs/{run_id}/audit").json()
        if not audit:
            pytest.skip("No audit records available for selective rollback test")
        first_id = audit[0]["audit_id"]
        body = client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": run_id, "audit_ids": [first_id], "dry_run": True},
        ).json()
        assert body["attempted"] == 1

    def test_rollback_response_has_correct_run_id(self, client):
        run_id = _scan_score_execute(client, live=False)
        body = client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": run_id, "dry_run": True},
        ).json()
        assert body["run_id"] == run_id

    def test_rollback_counts_sum_to_attempted(self, client):
        run_id = _scan_score_execute(client, live=False)
        body = client.post(
            "/api/v1/optimizer/rollback",
            json={"run_id": run_id, "dry_run": True},
        ).json()
        assert body["rolled_back"] + body["skipped"] + body["failed"] == body["attempted"]
