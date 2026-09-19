from typing import Optional
from sqlmodel import SQLModel, Field


class Company(SQLModel, table=True):
    __tablename__ = "companies"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    website: Optional[str] = Field(default=None)
    careers_url: Optional[str] = Field(default=None)
    cin: Optional[str] = Field(default=None, description="Corporate Identification Number (MCA India)")
