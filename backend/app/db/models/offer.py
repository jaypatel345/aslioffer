from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


class Offer(SQLModel, table=True):
    __tablename__ = "offers"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    source_type: str = Field(description="e.g. pdf, screenshot, email, text")
    raw_content: str = Field(description="Extracted text or content of the offer")
    risk_score: Optional[float] = Field(default=None, description="Score between 0.0 and 1.0")
    status: str = Field(default="PENDING", description="PENDING, PROCESSING, COMPLETED, FAILED")
    risk_level: Optional[str] = Field(default=None, description="VERIFIED, NEEDS_REVIEW, HIGH_RISK")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
