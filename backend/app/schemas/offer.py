from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class OfferCreate(BaseModel):
    title: str = Field(..., json_schema_extra={"example": "Software Engineer Offer Letter - TechCorp"})
    source_type: str = Field(..., description="pdf, screenshot, email, text", json_schema_extra={"example": "pdf"})
    raw_content: str = Field(..., json_schema_extra={"example": "Offer text content..."})


class OfferRead(BaseModel):
    id: int
    title: str
    source_type: str
    raw_content: str
    risk_score: Optional[float] = None
    status: str
    risk_level: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OfferUploadResponse(BaseModel):
    offer_id: int
    title: str
    status: str
    message: str
