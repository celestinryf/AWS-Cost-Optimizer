from datetime import datetime, timedelta, timezone
import logging
import uuid

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client

from app.models import Recommendation, RecommendationType, RiskLevel, ScanRequest, StorageClass

_log = logging.getLogger(__name__)

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

    def __init__(self, s3_client: S3Client | None = None) -> None:
        self._s3: S3Client | None = s3_client

    @property
    def s3(self) -> S3Client:
        if self._s3 is None:
            self._s3 = boto3.client("s3")  # pyright: ignore[reportUnknownMemberType]
        return self._s3

    def scan(self, request: ScanRequest) -> list[Recommendation]:
        excluded = set(request.exclude_buckets)

        if request.include_buckets:
            buckets = [b for b in request.include_buckets if b not in excluded]
        else:
            try:
                resp = self.s3.list_buckets()
                buckets = [
                    name for b in resp.get("Buckets", [])
                    if (name := b.get("Name")) is not None and name not in excluded
                ]
            except ClientError:
                buckets = []

        cold_days = request.cold_days
        stale_days = request.stale_days
        multipart_days = request.multipart_days
        target_class = request.target_storage_class

        recommendations: list[Recommendation] = []
        for bucket in buckets:
            recommendations.extend(
                self._scan_bucket(bucket, request.max_objects_per_bucket, cold_days, stale_days, multipart_days, target_class)
            )
        return recommendations

    def _scan_bucket(
        self,
        bucket: str,
        max_objects: int,
        cold_days: int,
        stale_days: int,
        multipart_days: int,
        target_class: StorageClass,
    ) -> list[Recommendation]:
        recommendations: list[Recommendation] = []

        object_recs, _total_size_bytes, standard_size_bytes = self._scan_objects(
            bucket, max_objects, cold_days, stale_days, target_class,
        )
        recommendations.extend(object_recs)
        lifecycle_rec = self._check_lifecycle(bucket, total_size_bytes=standard_size_bytes)
        if lifecycle_rec:
            recommendations.append(lifecycle_rec)
        recommendations.extend(self._check_multipart_uploads(bucket, multipart_days))

        return recommendations

    def _scan_objects(
        self, bucket: str, max_objects: int, cold_days: int, stale_days: int, target_class: StorageClass,
    ) -> tuple[list[Recommendation], int, int]:
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

                    key = obj.get("Key")
                    last_modified = obj.get("LastModified")
                    if key is None or last_modified is None:
                        continue
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
                    age_days = (now - last_modified).days
                    size_gb = size_bytes / (1024 ** 3)
                    total_size_bytes += size_bytes
                    if storage_class_raw == "STANDARD":
                        standard_size_bytes += size_bytes

                    if age_days >= stale_days:
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
                    elif age_days >= cold_days and storage_class_raw == "STANDARD":
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
                            recommended_action=f"Transition to {target_class.value}",
                            estimated_monthly_savings=savings,
                            size_bytes=size_bytes,
                            storage_class=storage_class,
                            last_modified=last_modified,
                            target_storage_class=target_class,
                        ))

                if count >= max_objects:
                    break

        except ClientError as e:
            code: str = str(e.response.get("Error", {}).get("Code", ""))
            if code not in ("AccessDenied", "NoSuchBucket", "AllAccessDisabled"):
                raise

        return recs, total_size_bytes, standard_size_bytes

    def _check_lifecycle(self, bucket: str, *, total_size_bytes: int = 0) -> Recommendation | None:
        try:
            self.s3.get_bucket_lifecycle_configuration(Bucket=bucket)
            return None  # lifecycle policy already exists
        except ClientError as e:
            code: str = str(e.response.get("Error", {}).get("Code", ""))
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

    def _check_multipart_uploads(self, bucket: str, multipart_days: int = 7) -> list[Recommendation]:
        recs: list[Recommendation] = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=multipart_days)

        try:
            paginator = self.s3.get_paginator("list_multipart_uploads")
            for page in paginator.paginate(Bucket=bucket):
                for upload in page.get("Uploads", []):
                    initiated = upload.get("Initiated")
                    upload_key = upload.get("Key")
                    upload_id = upload.get("UploadId")
                    if initiated is None or upload_key is None or upload_id is None:
                        continue
                    if initiated < cutoff:
                        recs.append(Recommendation(
                            id=str(uuid.uuid4()),
                            bucket=bucket,
                            key=upload_key,
                            recommendation_type=RecommendationType.DELETE_INCOMPLETE_UPLOAD,
                            risk_level=RiskLevel.LOW,
                            reason=(
                                f"Multipart upload has been incomplete for "
                                f"{(now - initiated).days} days."
                            ),
                            recommended_action="Abort incomplete multipart upload",
                            estimated_monthly_savings=0.0,
                            size_bytes=0,
                            upload_id=upload_id,
                            last_modified=initiated,
                        ))
        except ClientError as e:
            code: str = str(e.response.get("Error", {}).get("Code", ""))
            if code not in ("AccessDenied", "NoSuchBucket", "NoSuchUpload"):
                raise

        return recs
