from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class OverallOutcome(str, Enum):
    HIGH_RISK = "HIGH_RISK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    CANNOT_VERIFY = "CANNOT_VERIFY"
    NO_STRONG_RISK_SIGNALS = "NO_STRONG_RISK_SIGNALS"


class AuthenticityStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"


class WarningSeverity(str, Enum):
    STRONG_ADVERSE = "STRONG_ADVERSE"
    REVIEW_CONCERN = "REVIEW_CONCERN"


class WarningBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class ExecutionStatus(str, Enum):
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    NOT_CHECKED = "not_checked"
    NOT_APPLICABLE = "not_applicable"


class ResolutionStatus(str, Enum):
    SUPPORTED = "supported"
    NO_MATCH = "no_match"
    UNCONFIRMED = "unconfirmed"
    CONFLICTING = "conflicting"


class WarningSignal(BaseModel):
    code: str
    severity: WarningSeverity
    title: str
    description: str
    source_agent: str
    evidence_refs: List[str] = Field(default_factory=list)


class CheckCoverageItem(BaseModel):
    check_id: str
    check_name: str
    agent_name: str
    execution_status: ExecutionStatus
    resolution_status: ResolutionStatus
    applicability: bool
    failure_reason: Optional[str] = None
    missing_input: Optional[str] = None
    evidence_refs: List[str] = Field(default_factory=list)
    remaining_uncertainty: Optional[str] = None


class CoverageSummary(BaseModel):
    total_checks: int
    applicable_checks: int
    completed_checks: int
    unavailable_checks: int
    not_applicable_checks: int
    completion_ratio: float = Field(
        ...,
        description="completed_checks / applicable_checks (0.0 if applicable_checks == 0). Not an authenticity confidence metric.",
    )
    unresolved_issues: List[str] = Field(default_factory=list)


class StructuredAssessment(BaseModel):
    overall_outcome: OverallOutcome
    authenticity_status: AuthenticityStatus = AuthenticityStatus.UNCONFIRMED
    warning_strength: float = Field(
        ...,
        description="Uncalibrated warning index between 0.0 and 1.0 (0.0 means no supported warning signals found). Never a fraud probability.",
    )
    warning_band: WarningBand
    supported_warning_signals: List[WarningSignal] = Field(default_factory=list)
    review_only_concerns: List[WarningSignal] = Field(default_factory=list)
    coverage_summary: CoverageSummary
    individual_checks: List[CheckCoverageItem] = Field(default_factory=list)
    supporting_evidence_refs: List[str] = Field(default_factory=list)
    unresolved_issues: List[str] = Field(default_factory=list)
    assessment_method: str = "structured_policy_v1"
    assessment_version: str = "1.0.0"
    policy_explanation: str
