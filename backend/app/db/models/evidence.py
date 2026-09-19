from typing import Optional
from sqlmodel import SQLModel, Field


class Evidence(SQLModel, table=True):
    __tablename__ = "evidence"

    id: Optional[int] = Field(default=None, primary_key=True)
    offer_id: int = Field(index=True, description="Associated Offer ID")
    source_url: str = Field(description="Live verification URL from SerpApi or public web")
    title: str = Field(description="Evidence title or summary")
    description: str = Field(description="Detailed verification finding")
    evidence_type: str = Field(description="COMPANY, RECRUITER, SALARY, SCAM_REPORT, DOMAIN")
    confidence: float = Field(default=1.0, description="Confidence score 0.0 to 1.0")
