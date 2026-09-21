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


class ExtractedData(BaseModel):
    company: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_email: Optional[str] = None
    recruiter_phone: Optional[str] = None
    job_role: Optional[str] = None
    salary: Optional[str] = None
    salary_amount: Optional[float] = None
    salary_period: Optional[str] = None
    joining_date: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    payment_request_detected: bool = False
    payment_amount: Optional[str] = None
    payment_method: Optional[str] = None
    flags: List[str] = Field(default_factory=list)
    raw_text: str = ""

    def to_extracted_entities(self) -> ExtractedEntities:
        """Adapter for backward compatibility with downstream agents and report generator."""
        return ExtractedEntities(
            company_name=self.company,
            recruiter_name=self.recruiter_name,
            recruiter_email=self.recruiter_email,
            recruiter_phone=self.recruiter_phone,
            role_title=self.job_role,
            offered_salary=self.salary,
            location=self.address or "Remote / India",
            demanded_fee=self.payment_amount if self.payment_request_detected else None,
            payment_method=self.payment_method,
            flags=list(self.flags),
        )


class DocumentExtractionResult(BaseModel):
    ocr_text: str
    entities: ExtractedData


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
