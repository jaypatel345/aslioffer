from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


class InvestigationRun(SQLModel, table=True):
    """One persisted investigation run (J3). The API serves it as a RunSnapshot.

    JSON columns hold contract-v1 objects (RunEvent[], InvestigationResult,
    RunError[]). A finished run is never modified again; force_refresh creates a
    new row with version + 1 and keeps this one.
    """

    __tablename__ = "investigation_runs"

    run_id: str = Field(primary_key=True)
    case_id: int = Field(index=True)
    version: int = Field(ge=1)
    previous_run_id: Optional[str] = None
    status: str = Field(index=True, description="QUEUED, RUNNING, COMPLETED, PARTIAL, FAILED")
    # Hash of the inputs (text + confirmed claims). A completed run is reused
    # without force_refresh only when the inputs are the same.
    input_hash: str
    confirmed_claims_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    events_json: str = Field(default="[]")
    report_json: Optional[str] = None
    errors_json: str = Field(default="[]")
