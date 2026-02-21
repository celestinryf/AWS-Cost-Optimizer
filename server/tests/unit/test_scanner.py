"""Unit tests for ScannerService."""

import pytest

from app.models import RecommendationType, ScanRequest
from app.scanner.service import ScannerService


@pytest.fixture()
def svc():
    return ScannerService()


@pytest.mark.unit
class TestScannerDefaults:
    def test_returns_recommendations_for_default_buckets(self, svc):
        """Default uses ["application-data", "archive-logs"] → 2 recs each → 4 total."""
        result = svc.scan(ScanRequest())
        assert len(result) == 4

    def test_two_recommendations_per_bucket(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["my-bucket"]))
        assert len(result) == 2

    def test_respects_include_buckets(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["bucket-a", "bucket-b"]))
        assert len(result) == 4

    def test_respects_exclude_buckets(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["a", "b"], exclude_buckets=["b"]))
        assert len(result) == 2

    def test_exclude_all_returns_empty(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["a"], exclude_buckets=["a"]))
        assert result == []

    def test_exclude_overlapping_subset(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["a", "b", "c"], exclude_buckets=["b"]))
        assert len(result) == 4  # 2 buckets remain

    def test_each_recommendation_has_unique_id(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["a", "b", "c"]))
        ids = [r.id for r in result]
        assert len(ids) == len(set(ids))

    def test_recommendation_types_are_valid_enum_values(self, svc):
        result = svc.scan(ScanRequest())
        types = {r.recommendation_type for r in result}
        for t in types:
            assert t in RecommendationType

    def test_estimated_monthly_savings_is_nonnegative(self, svc):
        result = svc.scan(ScanRequest())
        for rec in result:
            assert rec.estimated_monthly_savings >= 0

    def test_size_bytes_is_nonnegative(self, svc):
        result = svc.scan(ScanRequest())
        for rec in result:
            assert rec.size_bytes >= 0

    def test_bucket_field_matches_requested_bucket(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["my-bucket"]))
        for rec in result:
            assert rec.bucket == "my-bucket"

    def test_returns_change_storage_class_and_lifecycle_per_bucket(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["x"]))
        types = [r.recommendation_type for r in result]
        assert RecommendationType.CHANGE_STORAGE_CLASS in types
        assert RecommendationType.ADD_LIFECYCLE_POLICY in types
