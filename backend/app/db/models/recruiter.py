from typing import Optional
from sqlmodel import SQLModel, Field


class Recruiter(SQLModel, table=True):
    __tablename__ = "recruiters"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None, index=True)
    email: Optional[str] = Field(default=None, index=True)
    phone: Optional[str] = Field(default=None, index=True)
    linkedin_url: Optional[str] = Field(default=None)
