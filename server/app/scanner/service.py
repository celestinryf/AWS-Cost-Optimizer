from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import uuid

import boto3
from botocore.exceptions import ClientError

from app.models import Recommendation, RecommendationType, RiskLevel, ScanRequest, StorageClass

_log = logging.getLogger(__name__)

_COLD_DAYS = 90        # STANDARD object older than this → CHANGE_STORAGE_CLASS
_STALE_DAYS = 365      # Any object older than this → DELETE_STALE_OBJECT
_MULTIPART_DAYS = 7    # Incomplete upload older than this → DELETE_INCOMPLETE_UPLOAD
_TARGET_CLASS = StorageClass.GLACIER_IR
_STANDARD_PRICE = 0.023   # $/GB/month
_GLACIER_IR_PRICE = 0.004


class ScannerService:
    """
    Scans S3 buckets and returns cost-optimization recommendations.

    When include_buckets is empty, all accessible buckets are scanned
    (minus exclude_buckets). Requires S3 read permissions:
    s3:ListAllMyBuckets, s3:ListBucket, s3:GetBucketLifecycleConfiguration,
    s3:ListBucketMultipartUploads.
    """

    def __init__(self, s3_client: Any = None) -> None:
        self._s3 = s3_client

    @property
    def s3(self) -> Any:
        if self._s3 is None:
            self._s3 = boto3.client("s3")
        return self._s3

    def scan(self, request: ScanRequest) -> list[Recommendation]:
        excluded = set(request.exclude_buckets)

        if request.include_buckets:
            buckets = [b for b in request.include_buckets if b not in excluded]
        else:
            try:
                resp = self.s3.list_buckets()
                buckets = [
                    b["Name"] for b in resp.get("Buckets", []) if b["Name"] not in excluded
                ]
            except ClientError:
                buckets = []

        recommendations: list[Recommendation] = []
        for bucket in buckets:
            recommendations.extend(
                self._scan_bucket(bucket, request.max_objects_per_bucket)
            )
        return recommendations

    def _scan_bucket(self, bucket: str, max_objects: int) -> list[Recommendation]:
        recommendations: list[Recommendation] = []

        object_recs, total_size_bytes, standard_size_bytes = self._scan_objects(bucket, max_objects)
        recommendations.extend(object_recs)
        lifecycle_rec = self._check_lifecycle(bucket, total_size_bytes=standard_size_bytes)
        if lifecycle_rec:
            recommendations.append(lifecycle_rec)
        recommendations.extend(self._check_multipart_uploads(bucket))

        return recommendations

    def _scan_objects(self, bucket: str, max_objects: int) -> tuple[list[Recommendation], int, int]:
        recs: list[Recommendation] = []
        now = datetime.now(timezone.utc)
        count = 0
        total_size_bytes = 0
        standard_size_bytes = 0

        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    if count >= max_objects:
                        break
                    count += 1

                    key: str = obj["Key"]
                    size_bytes: int = obj.get("Size", 0)
                    storage_class_raw: str = obj.get("StorageClass", "STANDARD")
                    if storage_class_raw in StorageClass._value2member_map_:
                        storage_class = StorageClass(storage_class_raw)
                    else:
                        _log.warning(
                            "Unknown S3 storage class %r for %s/%s — not in StorageClass enum",
                            storage_class_raw, bucket, key,
                        )
                        storage_class = None
                    last_modified: datetime = obj["LastModified"]
                    age_days = (now - last_modified).days
                    size_gb = size_bytes / (1024 ** 3)
                    total_size_bytes += size_bytes
                    if storage_class_raw == "STANDARD":
                        standard_size_bytes += size_bytes

                    if age_days >= _STALE_DAYS:
                        recs.append(Recommendation(
                            id=str(uuid.uuid4()),
                            bucket=bucket,
                            key=key,
                            recommendation_type=RecommendationType.DELETE_STALE_OBJECT,
                            risk_level=RiskLevel.HIGH,
                            reason=(
                                f"Object has not been modified in {age_days} days "
                                f"({age_days // 365} year(s))."
                            ),
                            recommended_action="Delete stale object",
                            estimated_monthly_savings=round(_STANDARD_PRICE * size_gb, 4),
                            size_bytes=size_bytes,
                            storage_class=storage_class,
                            last_modified=last_modified,
                        ))
                    elif age_days >= _COLD_DAYS and storage_class_raw == "STANDARD":
                        savings = round((_STANDARD_PRICE - _GLACIER_IR_PRICE) * size_gb, 4)
                        recs.append(Recommendation(
                            id=str(uuid.uuid4()),
                            bucket=bucket,
                            key=key,
                            recommendation_type=RecommendationType.CHANGE_STORAGE_CLASS,
                            risk_level=RiskLevel.MEDIUM,
                            reason=(
                                f"Object has been in STANDARD storage for {age_days} days "
                                f"without modification."
                            ),
                            recommended_action=f"Transition to {_TARGET_CLASS.value}",
                            estimated_monthly_savings=savings,
                            size_bytes=size_bytes,
                            storage_class=storage_class,
                            last_modified=last_modified,
                            target_storage_class=_TARGET_CLASS,
                        ))

                if count >= max_objects:
                    break

        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("AccessDenied", "NoSuchBucket", "AllAccessDisabled"):
                raise

        return recs, total_size_bytes, standard_size_bytes

    def _check_lifecycle(self, bucket: str, *, total_size_bytes: int = 0) -> Recommendation | None:
        try:
            self.s3.get_bucket_lifecycle_configuration(Bucket=bucket)
            return None  # lifecycle policy already exists
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "NoSuchLifecycleConfiguration":
                size_gb = total_size_bytes / (1024 ** 3)
                estimated_savings = round((_STANDARD_PRICE - _GLACIER_IR_PRICE) * size_gb, 4)
                return Recommendation(
                    id=str(uuid.uuid4()),
                    bucket=bucket,
                    key=None,
                    recommendation_type=RecommendationType.ADD_LIFECYCLE_POLICY,
                    risk_level=RiskLevel.LOW,
                    reason="Bucket has no lifecycle policy for archival or multipart cleanup.",
                    recommended_action=(
                        "Add lifecycle rules for 90-day archive and 7-day multipart abort."
                    ),
                    estimated_monthly_savings=estimated_savings,
                    size_bytes=0,
                    storage_class=None,
                    last_modified=None,
                )
            if code not in ("AccessDenied", "NoSuchBucket"):
                raise
            return None

    def _check_multipart_uploads(self, bucket: str) -> list[Recommendation]:
        recs: list[Recommendation] = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=_MULTIPART_DAYS)

        try:
            paginator = self.s3.get_paginator("list_multipart_uploads")
            for page in paginator.paginate(Bucket=bucket):
                for upload in page.get("Uploads", []):
                    initiated: datetime = upload["Initiated"]
                    if initiated < cutoff:
                        recs.append(Recommendation(
                            id=str(uuid.uuid4()),
                            bucket=bucket,
                            key=upload["Key"],
                            recommendation_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
                            risk_level=RiskLevel.LOW,
                            reason=(
                                f"Multipart upload has been incomplete for "
                                f"{(now - initiated).days} days."
                            ),
                            recommended_action="Abort incomplete multipart upload",
                            estimated_monthly_savings=0.0,
                            size_bytes=0,
                            upload_id=upload["UploadId"],
                            last_modified=initiated,
                        ))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("AccessDenied", "NoSuchBucket", "NoSuchUpload"):
                raise

        return recs
