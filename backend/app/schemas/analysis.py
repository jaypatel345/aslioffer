from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    VERIFIED = "VERIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    HIGH_RISK = "HIGH_RISK"


class ExtractedEntities(BaseModel):
    company_name: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    recruiter_phone: Optional[str] = None
    role_title: Optional[str] = None
    offered_salary: Optional[str] = None
    location: Optional[str] = None
    demanded_fee: Optional[str] = None
    payment_method: Optional[str] = None
    flags: List[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    source_url: str
    title: str
    description: str
    evidence_type: str
    confidence: float


class AgentFinding(BaseModel):
    agent_name: str
    verdict: str
    confidence: float
    summary: str
    evidence: List[EvidenceItem] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class AnalysisRequest(BaseModel):
    offer_id: int
    force_refresh: bool = False


class VerificationReport(BaseModel):
    offer_id: int
    title: str
    risk_level: RiskLevel
    risk_score: float = Field(..., description="0.0 (safest) to 1.0 (highest risk)")
    summary: str
    extracted_entities: ExtractedEntities
    findings: List[AgentFinding]
    red_flags: List[str]
    green_flags: List[str]
    official_company_info: Dict[str, Optional[str]]
    recommended_actions: List[str]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
