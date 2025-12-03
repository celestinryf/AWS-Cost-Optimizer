# scoring/risk_scorer.py
"""
Risk scoring engine for cost optimization recommendations.

Evaluates each recommendation based on multiple factors:
- Object age and access patterns
- Size and potential impact
- Reversibility of the action
- Confidence in the recommendation
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from models import Recommendation, RecommendationType, RiskLevel


class ConfidenceLevel(Enum):
    """How confident we are in the recommendation."""
    HIGH = "high"       # 90%+ confident this is correct
    MEDIUM = "medium"   # 70-90% confident
    LOW = "low"         # <70% confident, needs review


@dataclass
class RiskScore:
    """Detailed risk assessment for a recommendation."""
    
    recommendation_id: str
    
    # Overall scores (0-100)
    risk_score: int          # Higher = riskier
    confidence_score: int    # Higher = more confident
    impact_score: int        # Higher = bigger impact (savings or damage)
    
    # Derived levels
    risk_level: RiskLevel
    confidence_level: ConfidenceLevel
    
    # Should we auto-execute?
    safe_to_automate: bool
    requires_approval: bool
    
    # Factors that influenced the score
    factors: list[str]
    
    # Recommendation for execution
    execution_recommendation: str
    
    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "impact_score": self.impact_score,
            "risk_level": self.risk_level.value,
            "confidence_level": self.confidence_level.value,
            "safe_to_automate": self.safe_to_automate,
            "requires_approval": self.requires_approval,
            "factors": self.factors,
            "execution_recommendation": self.execution_recommendation,
        }


class RiskScorer:
    """Scores recommendations based on risk factors."""
    
    # Weights for different factors (must sum to 100)
    WEIGHTS = {
        "reversibility": 30,      # Can we undo this?
        "data_loss_risk": 25,     # Could we lose data?
        "age_confidence": 20,     # How old is the object?
        "size_impact": 15,        # How big is the object?
        "access_pattern": 10,     # Do we know access patterns?
    }
    
    # Actions and their base reversibility scores (0 = irreversible, 100 = fully reversible)
    REVERSIBILITY_SCORES = {
        RecommendationType.CHANGE_STORAGE_CLASS: 90,      # Can change back
        RecommendationType.DELETE_INCOMPLETE_UPLOAD: 100, # No data loss
        RecommendationType.ADD_LIFECYCLE_POLICY: 100,     # Can remove policy
        RecommendationType.DELETE_OLD_VERSION: 70,        # Version is gone but current exists
        RecommendationType.DELETE_STALE_OBJECT: 0,        # Irreversible
    }
    
    def __init__(self):
        self.scores: dict[str, RiskScore] = {}
    
    def score_recommendation(self, rec: Recommendation) -> RiskScore:
        """
        Calculate risk score for a single recommendation.
        
        Returns a RiskScore with detailed assessment.
        """
        factors = []
        
        # 1. Reversibility score
        reversibility = self.REVERSIBILITY_SCORES.get(rec.recommendation_type, 50)
        if reversibility >= 80:
            factors.append(f"✓ Action is reversible ({rec.recommendation_type.value})")
        elif reversibility >= 50:
            factors.append(f"⚠ Action is partially reversible")
        else:
            factors.append(f"✗ Action is NOT reversible - data will be permanently deleted")
        
        # 2. Data loss risk
        data_loss_risk = self._calculate_data_loss_risk(rec)
        if data_loss_risk > 70:
            factors.append(f"✗ High data loss risk")
        elif data_loss_risk > 30:
            factors.append(f"⚠ Moderate data loss risk")
        else:
            factors.append(f"✓ Low data loss risk")
        
        # 3. Age confidence (older = safer to modify)
        age_confidence = self._calculate_age_confidence(rec)
        if age_confidence >= 80:
            factors.append(f"✓ Object is very old - high confidence it's unused")
        elif age_confidence >= 50:
            factors.append(f"⚠ Object age suggests it may be unused")
        else:
            factors.append(f"✗ Object is relatively new - low confidence")
        
        # 4. Size impact
        size_impact = self._calculate_size_impact(rec)
        if rec.size_bytes > 1024 * 1024 * 1024:  # > 1 GB
            factors.append(f"⚠ Large object ({rec.size_bytes / (1024**3):.1f} GB)")
        
        # 5. Access pattern confidence
        access_confidence = self._calculate_access_confidence(rec)
        if access_confidence < 50:
            factors.append(f"⚠ Limited access pattern data available")
        
        # Calculate weighted risk score (0-100, higher = riskier)
        # Invert reversibility and age_confidence since higher values mean LOWER risk
        risk_score = int(
            (100 - reversibility) * self.WEIGHTS["reversibility"] / 100 +
            data_loss_risk * self.WEIGHTS["data_loss_risk"] / 100 +
            (100 - age_confidence) * self.WEIGHTS["age_confidence"] / 100 +
            size_impact * self.WEIGHTS["size_impact"] / 100 +
            (100 - access_confidence) * self.WEIGHTS["access_pattern"] / 100
        )
        
        # Confidence score (inverse relationship with some risk factors)
        confidence_score = int((age_confidence + access_confidence + reversibility) / 3)
        
        # Impact score based on savings and size
        impact_score = self._calculate_impact_score(rec)
        
        # Determine levels
        risk_level = self._score_to_risk_level(risk_score)
        confidence_level = self._score_to_confidence_level(confidence_score)
        
        # Automation decision
        safe_to_automate = (
            risk_score < 30 and 
            confidence_score >= 70 and
            rec.recommendation_type != RecommendationType.DELETE_STALE_OBJECT
        )
        
        requires_approval = (
            risk_score >= 50 or 
            rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT or
            rec.size_bytes > 10 * 1024 * 1024 * 1024  # > 10 GB
        )
        
        # Execution recommendation
        execution_recommendation = self._get_execution_recommendation(
            risk_score, confidence_score, safe_to_automate, requires_approval
        )
        
        score = RiskScore(
            recommendation_id=rec.id,
            risk_score=risk_score,
            confidence_score=confidence_score,
            impact_score=impact_score,
            risk_level=risk_level,
            confidence_level=confidence_level,
            safe_to_automate=safe_to_automate,
            requires_approval=requires_approval,
            factors=factors,
            execution_recommendation=execution_recommendation,
        )
        
        self.scores[rec.id] = score
        return score
    
    def _calculate_data_loss_risk(self, rec: Recommendation) -> int:
        """Calculate risk of permanent data loss (0-100)."""
        if rec.recommendation_type == RecommendationType.DELETE_STALE_OBJECT:
            return 100
        elif rec.recommendation_type == RecommendationType.DELETE_OLD_VERSION:
            return 60
        elif rec.recommendation_type == RecommendationType.DELETE_INCOMPLETE_UPLOAD:
            return 10  # Incomplete uploads aren't usable anyway
        elif rec.recommendation_type == RecommendationType.CHANGE_STORAGE_CLASS:
            return 5   # Data still exists, just different storage
        elif rec.recommendation_type == RecommendationType.ADD_LIFECYCLE_POLICY:
            return 0   # Policy can be removed
        return 50
    
    def _calculate_age_confidence(self, rec: Recommendation) -> int:
        """Calculate confidence based on object age (0-100)."""
        if not rec.last_modified:
            return 30  # No data, low confidence
        
        now = datetime.now(timezone.utc)
        days_old = (now - rec.last_modified).days
        
        if days_old >= 365:
            return 95  # Very old, high confidence it's unused
        elif days_old >= 180:
            return 80
        elif days_old >= 90:
            return 65
        elif days_old >= 30:
            return 40
        else:
            return 20  # Recent object, low confidence
    
    def _calculate_access_confidence(self, rec: Recommendation) -> int:
        """
        Calculate confidence based on access pattern data (0-100).
        
        Note: S3 doesn't provide last-accessed time by default.
        This would improve with S3 Storage Lens or CloudWatch metrics.
        """
        # Without access logging enabled, we have limited data
        # Base confidence on what we do know
        if rec.last_modified:
            return 50  # We at least know modification date
        return 30
    
    def _calculate_size_impact(self, rec: Recommendation) -> int:
        """Calculate impact score based on size (0-100)."""
        size_gb = rec.size_bytes / (1024 ** 3)
        
        if size_gb >= 100:
            return 100
        elif size_gb >= 10:
            return 80
        elif size_gb >= 1:
            return 50
        elif size_gb >= 0.1:
            return 30
        else:
            return 10
    
    def _calculate_impact_score(self, rec: Recommendation) -> int:
        """Calculate overall impact (savings potential) score (0-100)."""
        # Based on monthly savings
        if rec.estimated_monthly_savings >= 100:
            return 100
        elif rec.estimated_monthly_savings >= 50:
            return 80
        elif rec.estimated_monthly_savings >= 10:
            return 60
        elif rec.estimated_monthly_savings >= 1:
            return 40
        else:
            return 20
    
    def _score_to_risk_level(self, score: int) -> RiskLevel:
        """Convert numeric score to risk level."""
        if score < 30:
            return RiskLevel.LOW
        elif score < 60:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.HIGH
    
    def _score_to_confidence_level(self, score: int) -> ConfidenceLevel:
        """Convert numeric score to confidence level."""
        if score >= 70:
            return ConfidenceLevel.HIGH
        elif score >= 50:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW
    
    def _get_execution_recommendation(
        self, 
        risk_score: int, 
        confidence_score: int,
        safe_to_automate: bool,
        requires_approval: bool
    ) -> str:
        """Generate human-readable execution recommendation."""
        if safe_to_automate:
            return "Safe to automate - low risk, high confidence"
        elif requires_approval:
            if risk_score >= 70:
                return "Manual review required - high risk action"
            else:
                return "Approval required before execution"
        elif confidence_score < 50:
            return "Gather more data before proceeding"
        else:
            return "Include in dry-run batch for validation"
    
    def get_automation_candidates(self) -> list[str]:
        """Return IDs of recommendations safe to automate."""
        return [
            rec_id for rec_id, score in self.scores.items()
            if score.safe_to_automate
        ]
    
    def get_approval_required(self) -> list[str]:
        """Return IDs of recommendations requiring approval."""
        return [
            rec_id for rec_id, score in self.scores.items()
            if score.requires_approval
        ]
    
    def get_summary(self) -> dict:
        """Get summary statistics of all scored recommendations."""
        if not self.scores:
            return {}
        
        return {
            "total_scored": len(self.scores),
            "safe_to_automate": len(self.get_automation_candidates()),
            "requires_approval": len(self.get_approval_required()),
            "average_risk_score": sum(s.risk_score for s in self.scores.values()) / len(self.scores),
            "average_confidence": sum(s.confidence_score for s in self.scores.values()) / len(self.scores),
            "by_risk_level": {
                "low": len([s for s in self.scores.values() if s.risk_level == RiskLevel.LOW]),
                "medium": len([s for s in self.scores.values() if s.risk_level == RiskLevel.MEDIUM]),
                "high": len([s for s in self.scores.values() if s.risk_level == RiskLevel.HIGH]),
            }
        }