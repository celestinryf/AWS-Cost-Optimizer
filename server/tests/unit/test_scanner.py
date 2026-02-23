"""Unit tests for ScannerService."""

import pytest
import boto3

from app.models import RecommendationType, ScanRequest
from app.scanner.service import ScannerService


@pytest.fixture()
def svc(s3_mock):
    """ScannerService backed by the moto S3 fixture."""
    return ScannerService(s3_client=s3_mock)


# ---------------------------------------------------------------------------
# Bucket resolution
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBucketResolution:
    def test_empty_include_scans_all_accessible_buckets(self, svc):
        """include_buckets=[] → list_buckets() → scans test-bucket → ≥1 rec."""
        result = svc.scan(ScanRequest())
        assert len(result) >= 1

    def test_include_buckets_restricts_scan(self, svc, s3_mock):
        """Only listed buckets are scanned."""
        s3_mock.create_bucket(Bucket="other-bucket")
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        assert all(r.bucket == "test-bucket" for r in result)

    def test_nonexistent_bucket_is_silently_skipped(self, svc):
        """Scanning a bucket that doesn't exist yields 0 recommendations."""
        result = svc.scan(ScanRequest(include_buckets=["ghost-bucket"]))
        assert result == []

    def test_exclude_all_returns_empty(self, svc):
        result = svc.scan(
            ScanRequest(include_buckets=["test-bucket"], exclude_buckets=["test-bucket"])
        )
        assert result == []

    def test_exclude_subset_only_scans_remaining(self, svc, s3_mock):
        s3_mock.create_bucket(Bucket="bucket-b")
        result = svc.scan(
            ScanRequest(include_buckets=["test-bucket", "bucket-b"], exclude_buckets=["bucket-b"])
        )
        assert all(r.bucket == "test-bucket" for r in result)

    def test_bucket_field_matches_scanned_bucket(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        for rec in result:
            assert rec.bucket == "test-bucket"

    def test_each_recommendation_has_unique_id(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        ids = [r.id for r in result]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Lifecycle policy detection
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLifecycleDetection:
    def test_lifecycle_policy_recommended_for_bucket_without_lifecycle(self, svc):
        """Fresh moto bucket has no lifecycle → ADD_LIFECYCLE_POLICY recommendation."""
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        types = [r.recommendation_type for r in result]
        assert RecommendationType.ADD_LIFECYCLE_POLICY in types

    def test_no_lifecycle_recommendation_if_policy_already_exists(self, svc, s3_mock):
        """Bucket with a lifecycle config → no ADD_LIFECYCLE_POLICY recommendation."""
        s3_mock.put_bucket_lifecycle_configuration(
            Bucket="test-bucket",
            LifecycleConfiguration={
                "Rules": [{
                    "ID": "existing-rule",
                    "Status": "Enabled",
                    "Filter": {"Prefix": ""},
                    "Expiration": {"Days": 365},
                }]
            },
        )
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        types = [r.recommendation_type for r in result]
        assert RecommendationType.ADD_LIFECYCLE_POLICY not in types

    def test_lifecycle_recommendation_has_bucket_set_and_no_key(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        lifecycle_recs = [
            r for r in result
            if r.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY
        ]
        assert len(lifecycle_recs) == 1
        assert lifecycle_recs[0].key is None
        assert lifecycle_recs[0].bucket == "test-bucket"


# ---------------------------------------------------------------------------
# Object-age-based recommendations (patched thresholds so moto objects qualify)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestObjectAgeRecommendations:
    def test_change_storage_class_recommended_for_standard_objects(self, svc, monkeypatch):
        """Patch _COLD_DAYS to -1 so all objects are 'cold' → CHANGE_STORAGE_CLASS rec."""
        monkeypatch.setattr("app.scanner.service._COLD_DAYS", -1)
        monkeypatch.setattr("app.scanner.service._STALE_DAYS", 9999)
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        types = [r.recommendation_type for r in result]
        assert RecommendationType.CHANGE_STORAGE_CLASS in types

    def test_delete_stale_object_recommended_for_very_old_objects(self, svc, monkeypatch):
        """Patch _STALE_DAYS to -1 so all objects are 'stale' → DELETE_STALE_OBJECT rec."""
        monkeypatch.setattr("app.scanner.service._STALE_DAYS", -1)
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        types = [r.recommendation_type for r in result]
        assert RecommendationType.DELETE_STALE_OBJECT in types

    def test_stale_object_takes_priority_over_storage_class(self, svc, monkeypatch):
        """When an object qualifies for both DELETE_STALE and CHANGE_CLASS,
        only DELETE_STALE is returned (not both)."""
        monkeypatch.setattr("app.scanner.service._STALE_DAYS", -1)
        monkeypatch.setattr("app.scanner.service._COLD_DAYS", -1)
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        for rec in result:
            if rec.key == "test/key.parquet":
                assert rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT

    def test_change_storage_class_only_for_standard_class(self, svc, s3_mock, monkeypatch):
        """Objects already in GLACIER_IR should NOT get a CHANGE_STORAGE_CLASS rec."""
        monkeypatch.setattr("app.scanner.service._COLD_DAYS", -1)
        monkeypatch.setattr("app.scanner.service._STALE_DAYS", 9999)
        s3_mock.put_object(
            Bucket="test-bucket",
            Key="glacier/file.parquet",
            Body=b"data",
            StorageClass="GLACIER_IR",
        )
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        for rec in result:
            if rec.key == "glacier/file.parquet":
                assert rec.recommendation_type != RecommendationType.CHANGE_STORAGE_CLASS

    def test_storage_class_transition_target_is_glacier_ir(self, svc, monkeypatch):
        monkeypatch.setattr("app.scanner.service._COLD_DAYS", -1)
        monkeypatch.setattr("app.scanner.service._STALE_DAYS", 9999)
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        for rec in result:
            if rec.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
                assert "GLACIER_IR" in rec.recommended_action


# ---------------------------------------------------------------------------
# Multipart upload detection
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMultipartUploadDetection:
    def test_incomplete_upload_recommended_for_old_multipart(self, svc, s3_mock, monkeypatch):
        """Patch _MULTIPART_DAYS to -1 so all multipart uploads qualify."""
        monkeypatch.setattr("app.scanner.service._MULTIPART_DAYS", -1)
        # Create an in-progress multipart upload
        resp = s3_mock.create_multipart_upload(Bucket="test-bucket", Key="uploads/data.bin")
        _ = resp["UploadId"]  # noqa: upload in progress
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        types = [r.recommendation_type for r in result]
        assert RecommendationType.DELETE_INCOMPLETE_UPLOAD in types

    def test_no_multipart_recommendation_if_no_uploads(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        types = [r.recommendation_type for r in result]
        assert RecommendationType.DELETE_INCOMPLETE_UPLOAD not in types


# ---------------------------------------------------------------------------
# Recommendation field validity
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRecommendationFieldValidity:
    def test_recommendation_types_are_valid_enum_values(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        for rec in result:
            assert rec.recommendation_type in RecommendationType

    def test_estimated_monthly_savings_is_nonnegative(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        for rec in result:
            assert rec.estimated_monthly_savings >= 0

    def test_size_bytes_is_nonnegative(self, svc):
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"]))
        for rec in result:
            assert rec.size_bytes >= 0

    def test_max_objects_per_bucket_limit_respected(self, svc, s3_mock, monkeypatch):
        """max_objects_per_bucket=1 → only 1 object scanned."""
        monkeypatch.setattr("app.scanner.service._COLD_DAYS", -1)
        monkeypatch.setattr("app.scanner.service._STALE_DAYS", 9999)
        # Add a second STANDARD object
        s3_mock.put_object(Bucket="test-bucket", Key="second/file.parquet", Body=b"y" * 512)
        # With max_objects=1, only 1 object-based rec should appear
        result = svc.scan(ScanRequest(include_buckets=["test-bucket"], max_objects_per_bucket=1))
        object_recs = [
            r for r in result
            if r.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS
        ]
        assert len(object_recs) == 1
