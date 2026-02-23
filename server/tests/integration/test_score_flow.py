"""Integration tests for POST /api/v1/optimizer/score."""

import pytest


def _scan(client, buckets=None):
    payload = {}
    if buckets:
        payload["include_buckets"] = buckets
    return client.post("/api/v1/optimizer/scan", json=payload).json()["run_id"]


@pytest.mark.integration
class TestScoreEndpoint:
    def test_score_after_scan_returns_200(self, client):
        run_id = _scan(client)
        resp = client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        assert resp.status_code == 200

    def test_score_response_status_is_scored(self, client):
        run_id = _scan(client)
        body = client.post("/api/v1/optimizer/score", json={"run_id": run_id}).json()
        assert body["status"] == "scored"

    def test_score_response_has_scores_list(self, client):
        run_id = _scan(client)
        body = client.post("/api/v1/optimizer/score", json={"run_id": run_id}).json()
        assert isinstance(body["scores"], list)
        assert len(body["scores"]) > 0

    def test_score_response_has_savings_summary(self, client):
        run_id = _scan(client)
        body = client.post("/api/v1/optimizer/score", json={"run_id": run_id}).json()
        assert "savings_summary" in body
        assert body["savings_summary"]["total_monthly_savings"] >= 0

    def test_score_response_has_approval_counts(self, client):
        run_id = _scan(client)
        body = client.post("/api/v1/optimizer/score", json={"run_id": run_id}).json()
        assert "safe_to_automate" in body
        assert "requires_approval" in body
        assert body["safe_to_automate"] >= 0
        assert body["requires_approval"] >= 0

    def test_score_updates_run_status_to_scored(self, client):
        run_id = _scan(client)
        client.post("/api/v1/optimizer/score", json={"run_id": run_id})
        run = client.get(f"/api/v1/optimizer/runs/{run_id}").json()
        assert run["status"] == "scored"

    def test_score_nonexistent_run_returns_404(self, client):
        resp = client.post("/api/v1/optimizer/score", json={"run_id": "does-not-exist"})
        assert resp.status_code == 404

    def test_score_missing_run_id_returns_422(self, client):
        resp = client.post("/api/v1/optimizer/score", json={})
        assert resp.status_code == 422
