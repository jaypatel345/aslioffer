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
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OfferUploadResponse(BaseModel):
    offer_id: int
    title: str
    status: str
    message: str
    # Returned once. Send it as the X-Case-Token header on every request for this
    # case; it is not stored in readable form and cannot be recovered.
    access_token: str
    expires_at: datetime
