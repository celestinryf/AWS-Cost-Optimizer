"""Integration tests for POST /api/v1/optimizer/scan."""

import pytest


@pytest.mark.integration
class TestScanEndpoint:
    def test_scan_returns_201(self, client):
        resp = client.post("/api/v1/optimizer/scan", json={})
        assert resp.status_code == 201

    def test_scan_response_has_run_id(self, client):
        body = client.post("/api/v1/optimizer/scan", json={}).json()
        assert "run_id" in body
        assert len(body["run_id"]) > 0

    def test_scan_response_status_is_scanned(self, client):
        body = client.post("/api/v1/optimizer/scan", json={}).json()
        assert body["status"] == "scanned"

    def test_scan_response_has_recommendations_list(self, client):
        body = client.post("/api/v1/optimizer/scan", json={}).json()
        assert isinstance(body["recommendations"], list)
        assert len(body["recommendations"]) > 0

    def test_scan_estimated_savings_is_nonnegative(self, client):
        body = client.post("/api/v1/optimizer/scan", json={}).json()
        assert body["estimated_monthly_savings"] >= 0

    def test_scan_with_include_buckets(self, client):
        body = client.post(
            "/api/v1/optimizer/scan",
            json={"include_buckets": ["test-bucket"]},
        ).json()
        assert len(body["recommendations"]) >= 1

    def test_scan_with_exclude_all_returns_empty(self, client):
        body = client.post(
            "/api/v1/optimizer/scan",
            json={"include_buckets": ["a"], "exclude_buckets": ["a"]},
        ).json()
        assert body["recommendations"] == []

    def test_scan_creates_retrievable_run(self, client):
        run_id = client.post("/api/v1/optimizer/scan", json={}).json()["run_id"]
        resp = client.get(f"/api/v1/optimizer/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == run_id

    def test_scan_invalid_max_objects_returns_422(self, client):
        resp = client.post("/api/v1/optimizer/scan", json={"max_objects_per_bucket": 0})
        assert resp.status_code == 422
