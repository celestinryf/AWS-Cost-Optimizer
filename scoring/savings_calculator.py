# scoring/savings_calculator.py
"""
Accurate savings calculator for S3 cost optimizations.

Accounts for:
- Storage class pricing differences
- Request costs for transitions
- Minimum storage duration charges
- Retrieval costs
"""

from dataclasses import dataclass
from typing import Optional

from models import Recommendation, RecommendationType


@dataclass
class SavingsEstimate:
    """Detailed savings breakdown."""
    
    recommendation_id: str
    
    # Monthly costs
    current_monthly_cost: float
    projected_monthly_cost: float
    monthly_savings: float
    
    # One-time costs
    transition_cost: float          # Cost to make the change
    minimum_duration_risk: float    # Potential early deletion fees
    
    # Net savings
    net_first_month: float          # Savings minus transition cost
    net_annual_savings: float       # Projected yearly savings
    
    # Break-even analysis
    break_even_days: Optional[int]  # Days until transition pays off
    
    # Confidence
    estimate_confidence: str        # "high", "medium", "low"
    assumptions: list[str]
    
    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "current_monthly_cost": round(self.current_monthly_cost, 4),
            "projected_monthly_cost": round(self.projected_monthly_cost, 4),
            "monthly_savings": round(self.monthly_savings, 4),
            "transition_cost": round(self.transition_cost, 4),
            "minimum_duration_risk": round(self.minimum_duration_risk, 4),
            "net_first_month": round(self.net_first_month, 4),
            "net_annual_savings": round(self.net_annual_savings, 2),
            "break_even_days": self.break_even_days,
            "estimate_confidence": self.estimate_confidence,
            "assumptions": self.assumptions,
        }


class SavingsCalculator:
    """
    Calculates accurate cost savings for S3 optimizations.
    
    Pricing based on us-east-1 as of 2024. Update for your region.
    """
    
    # Storage pricing (per GB/month)
    STORAGE_PRICING = {
        "STANDARD": 0.023,
        "INTELLIGENT_TIERING": 0.023,  # Frequent access tier
        "INTELLIGENT_TIERING_IA": 0.0125,  # Infrequent access tier
        "STANDARD_IA": 0.0125,
        "ONEZONE_IA": 0.01,
        "GLACIER_IR": 0.004,
        "GLACIER_FR": 0.0036,  # Flexible retrieval
        "GLACIER": 0.0036,
        "DEEP_ARCHIVE": 0.00099,
    }
    
    # Transition request costs (per 1000 requests)
    TRANSITION_COSTS = {
        "STANDARD_IA": 0.01,
        "ONEZONE_IA": 0.01,
        "INTELLIGENT_TIERING": 0.0025,
        "GLACIER_IR": 0.02,
        "GLACIER": 0.03,
        "DEEP_ARCHIVE": 0.05,
    }
    
    # Minimum storage duration (days) - charged if deleted/transitioned early
    MIN_STORAGE_DURATION = {
        "STANDARD_IA": 30,
        "ONEZONE_IA": 30,
        "GLACIER_IR": 90,
        "GLACIER": 90,
        "DEEP_ARCHIVE": 180,
    }
    
    # Retrieval costs (per GB) - in case user needs to access
    RETRIEVAL_COSTS = {
        "STANDARD": 0,
        "STANDARD_IA": 0.01,
        "GLACIER_IR": 0.03,
        "GLACIER": 0.01,  # Standard retrieval
        "DEEP_ARCHIVE": 0.02,
    }
    
    def calculate_savings(self, rec: Recommendation) -> SavingsEstimate:
        """
        Calculate detailed savings estimate for a recommendation.
        """
        assumptions = []
        
        if rec.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
            return self._calculate_storage_class_savings(rec)
        
        elif rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
            return self._calculate_deletion_savings(rec)
        
        elif rec.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
            return self._calculate_multipart_savings(rec)
        
        elif rec.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
            return self._calculate_lifecycle_savings(rec)
        
        elif rec.recommendation_type == RecommendationType.DELETE_OLD_VERSION:
            return self._calculate_version_savings(rec)
        
        # Default fallback
        return SavingsEstimate(
            recommendation_id=rec.id,
            current_monthly_cost=0,
            projected_monthly_cost=0,
            monthly_savings=rec.estimated_monthly_savings,
            transition_cost=0,
            minimum_duration_risk=0,
            net_first_month=rec.estimated_monthly_savings,
            net_annual_savings=rec.estimated_monthly_savings * 12,
            break_even_days=0,
            estimate_confidence="low",
            assumptions=["Unable to calculate detailed savings"],
        )
    
    def _calculate_storage_class_savings(self, rec: Recommendation) -> SavingsEstimate:
        """Calculate savings for storage class transition."""
        assumptions = []
        
        size_gb = rec.size_bytes / (1024 ** 3)
        current_class = rec.storage_class or "STANDARD"
        
        # Determine target class from recommendation
        target_class = self._parse_target_class(rec.recommended_action)
        
        # Current monthly cost
        current_rate = self.STORAGE_PRICING.get(current_class, 0.023)
        current_monthly = size_gb * current_rate
        
        # Projected monthly cost
        target_rate = self.STORAGE_PRICING.get(target_class, 0.004)
        projected_monthly = size_gb * target_rate
        
        # Monthly savings
        monthly_savings = current_monthly - projected_monthly
        
        # Transition cost (one-time)
        transition_rate = self.TRANSITION_COSTS.get(target_class, 0.02)
        transition_cost = transition_rate / 1000  # Per object
        
        assumptions.append(f"Transition from {current_class} to {target_class}")
        assumptions.append(f"Object size: {size_gb:.2f} GB")
        
        # Minimum duration risk
        min_days = self.MIN_STORAGE_DURATION.get(target_class, 0)
        if min_days > 0:
            # If deleted before min duration, charged for full period
            min_duration_risk = projected_monthly * (min_days / 30)
            assumptions.append(f"Minimum storage duration: {min_days} days")
        else:
            min_duration_risk = 0
        
        # Net calculations
        net_first_month = monthly_savings - transition_cost
        net_annual = (monthly_savings * 12) - transition_cost
        
        # Break-even analysis
        if monthly_savings > 0:
            break_even_days = int((transition_cost / monthly_savings) * 30)
        else:
            break_even_days = None
        
        # Confidence based on data quality
        if rec.last_modified and rec.size_bytes > 0:
            confidence = "high"
        elif rec.size_bytes > 0:
            confidence = "medium"
        else:
            confidence = "low"
        
        return SavingsEstimate(
            recommendation_id=rec.id,
            current_monthly_cost=current_monthly,
            projected_monthly_cost=projected_monthly,
            monthly_savings=monthly_savings,
            transition_cost=transition_cost,
            minimum_duration_risk=min_duration_risk,
            net_first_month=net_first_month,
            net_annual_savings=net_annual,
            break_even_days=break_even_days,
            estimate_confidence=confidence,
            assumptions=assumptions,
        )
    
    def _calculate_deletion_savings(self, rec: Recommendation) -> SavingsEstimate:
        """Calculate savings for deleting stale objects."""
        size_gb = rec.size_bytes / (1024 ** 3)
        storage_class = rec.storage_class or "STANDARD"
        
        rate = self.STORAGE_PRICING.get(storage_class, 0.023)
        monthly_cost = size_gb * rate
        
        return SavingsEstimate(
            recommendation_id=rec.id,
            current_monthly_cost=monthly_cost,
            projected_monthly_cost=0,
            monthly_savings=monthly_cost,
            transition_cost=0,
            minimum_duration_risk=0,
            net_first_month=monthly_cost,
            net_annual_savings=monthly_cost * 12,
            break_even_days=0,
            estimate_confidence="high",
            assumptions=[
                f"Complete deletion of {size_gb:.2f} GB",
                f"Current storage class: {storage_class}",
                "Warning: This action is irreversible",
            ],
        )
    
    def _calculate_multipart_savings(self, rec: Recommendation) -> SavingsEstimate:
        """Calculate savings for aborting incomplete multipart uploads."""
        # Multipart uploads are charged at STANDARD rate
        size_gb = rec.size_bytes / (1024 ** 3) if rec.size_bytes else 0.01
        
        monthly_cost = size_gb * self.STORAGE_PRICING["STANDARD"]
        
        return SavingsEstimate(
            recommendation_id=rec.id,
            current_monthly_cost=monthly_cost,
            projected_monthly_cost=0,
            monthly_savings=monthly_cost,
            transition_cost=0,
            minimum_duration_risk=0,
            net_first_month=monthly_cost,
            net_annual_savings=monthly_cost * 12,
            break_even_days=0,
            estimate_confidence="medium" if rec.size_bytes else "low",
            assumptions=[
                "Incomplete uploads charged at STANDARD rate",
                "No data loss - upload was never completed",
            ],
        )
    
    def _calculate_lifecycle_savings(self, rec: Recommendation) -> SavingsEstimate:
        """Calculate estimated savings from adding lifecycle policy."""
        # This is an estimate based on typical patterns
        size_gb = rec.size_bytes / (1024 ** 3)
        
        # Assume 30% of data could be transitioned
        estimated_savings = size_gb * 0.30 * (0.023 - 0.004)  # STANDARD to GLACIER_IR
        
        return SavingsEstimate(
            recommendation_id=rec.id,
            current_monthly_cost=size_gb * 0.023,
            projected_monthly_cost=size_gb * 0.023 * 0.70 + size_gb * 0.004 * 0.30,
            monthly_savings=estimated_savings,
            transition_cost=0,
            minimum_duration_risk=0,
            net_first_month=estimated_savings,
            net_annual_savings=estimated_savings * 12,
            break_even_days=0,
            estimate_confidence="low",
            assumptions=[
                "Estimated 30% of data eligible for archival",
                "Actual savings depend on access patterns",
                "Lifecycle policy has no direct cost",
            ],
        )
    
    def _calculate_version_savings(self, rec: Recommendation) -> SavingsEstimate:
        """Calculate savings for deleting old versions."""
        size_gb = rec.size_bytes / (1024 ** 3)
        storage_class = rec.storage_class or "STANDARD"
        
        rate = self.STORAGE_PRICING.get(storage_class, 0.023)
        monthly_cost = size_gb * rate
        
        return SavingsEstimate(
            recommendation_id=rec.id,
            current_monthly_cost=monthly_cost,
            projected_monthly_cost=0,
            monthly_savings=monthly_cost,
            transition_cost=0,
            minimum_duration_risk=0,
            net_first_month=monthly_cost,
            net_annual_savings=monthly_cost * 12,
            break_even_days=0,
            estimate_confidence="high",
            assumptions=[
                f"Deletion of old version ({size_gb:.2f} GB)",
                "Current version remains unchanged",
            ],
        )
    
    def _parse_target_class(self, action: str) -> str:
        """Parse target storage class from recommendation action."""
        action_lower = action.lower()
        
        if "deep_archive" in action_lower:
            return "DEEP_ARCHIVE"
        elif "glacier_ir" in action_lower:
            return "GLACIER_IR"
        elif "glacier" in action_lower:
            return "GLACIER"
        elif "intelligent" in action_lower:
            return "INTELLIGENT_TIERING"
        elif "onezone" in action_lower:
            return "ONEZONE_IA"
        elif "standard_ia" in action_lower:
            return "STANDARD_IA"
        else:
            return "GLACIER_IR"  # Default recommendation
    
    def calculate_total_savings(self, estimates: list[SavingsEstimate]) -> dict:
        """Calculate aggregate savings across all estimates."""
        return {
            "total_monthly_savings": sum(e.monthly_savings for e in estimates),
            "total_annual_savings": sum(e.net_annual_savings for e in estimates),
            "total_transition_costs": sum(e.transition_cost for e in estimates),
            "net_first_month": sum(e.net_first_month for e in estimates),
            "count": len(estimates),
            "high_confidence_count": len([e for e in estimates if e.estimate_confidence == "high"]),
        }