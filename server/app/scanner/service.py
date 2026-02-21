from datetime import datetime, timedelta, timezone
import uuid

from app.models import Recommendation, RecommendationType, RiskLevel, ScanRequest


class ScannerService:
    """
    API-facing scan service.

    This currently returns deterministic recommendations suitable for client integration.
    Replace internals with real S3 scanning without changing API contracts.
    """

    def scan(self, request: ScanRequest) -> list[Recommendation]:
        buckets = request.include_buckets or ["application-data", "archive-logs"]
        excluded = set(request.exclude_buckets)
        scan_targets = [bucket for bucket in buckets if bucket not in excluded]

        recommendations: list[Recommendation] = []
        now = datetime.now(timezone.utc)

        for bucket in scan_targets:
            recommendations.append(
                Recommendation(
                    id=str(uuid.uuid4()),
                    bucket=bucket,
                    key="events/2024/01/legacy-events.parquet",
                    recommendation_type=RecommendationType.CHANGE_STORAGE_CLASS,
                    risk_level=RiskLevel.MEDIUM,
                    reason="Object appears cold based on age and path.",
                    recommended_action="Transition to GLACIER_IR",
                    estimated_monthly_savings=12.6,
                    size_bytes=8 * 1024 * 1024 * 1024,
                    storage_class="STANDARD",
                    last_modified=now - timedelta(days=220),
                )
            )

            recommendations.append(
                Recommendation(
                    id=str(uuid.uuid4()),
                    bucket=bucket,
                    key=None,
                    recommendation_type=RecommendationType.ADD_LIFECYCLE_POLICY,
                    risk_level=RiskLevel.LOW,
                    reason="Bucket has no lifecycle policy for archival or multipart cleanup.",
                    recommended_action="Add lifecycle rules for 90-day archive and 7-day multipart abort.",
                    estimated_monthly_savings=3.1,
                    size_bytes=0,
                    storage_class=None,
                    last_modified=None,
                )
            )

        return recommendations

