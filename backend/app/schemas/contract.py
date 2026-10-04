"""AsliOffer API contract v1 — the shared wire format between the investigator,
the API/run service and the frontend.

Owned by Jay (schemas lane). Shriraj's investigator returns ``InvestigationResult``;
the run service wraps it in ``RunSnapshot``; the frontend mirrors these models in
``frontend/src/types/index.ts``. Human-readable spec and change rules live in
``docs/api-contract.md``; canonical example payloads live in
``docs/contract/v1/examples/`` and are validated by ``tests/test_api_contract.py``.

Rules encoded here (not just documented):

* Unknown fields are rejected (``extra="forbid"``) so silent renames and ad-hoc
  fields such as ``fraud_probability`` fail loudly instead of drifting.
* Evidence references must resolve inside the same run; an assessment cannot
  cite evidence that was never retrieved.
* A failed retrieval is never evidence for or against a claim, and DEMO evidence
  can only appear in an explicitly demo-mode run.
* ``authenticity_status`` stays ``UNCONFIRMED``: only the employer can confirm an
  offer, and no field in this contract represents that.
* Coverage counts describe completeness, never fraud likelihood.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.risk.assessment_models import AuthenticityStatus, OverallOutcome

CONTRACT_VERSION = "1.0.0"

__all__ = [
    "CONTRACT_VERSION",
    "OverallOutcome",
    "AuthenticityStatus",
    "SourceType",
    "ClaimKind",
    "ExtractionStatus",
    "SourceKind",
    "RetrievalStatus",
    "SourceTier",
    "EvidenceRelation",
    "ClaimStatus",
    "RunStatus",
    "EventStatus",
    "ConfirmedClaim",
    "CaseInput",
    "Claim",
    "EvidenceRecord",
    "AssessedClaim",
    "Coverage",
    "ConfirmationRoute",
    "ToolCall",
    "RunError",
    "InvestigationResult",
    "RunEvent",
    "RunSnapshot",
    "ErrorResponse",
]


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# --------------------------------------------------------------------------- enums


class SourceType(str, Enum):
    PDF = "pdf"
    SCREENSHOT = "screenshot"
    EMAIL = "email"
    TEXT = "text"


class ClaimKind(str, Enum):
    EMPLOYER = "employer"
    SENDER_EMAIL = "sender_email"
    CONTACT_PHONE = "contact_phone"
    RECRUITER_NAME = "recruiter_name"
    ROLE = "role"
    LOCATION = "location"
    JOB_REFERENCE = "job_reference"
    APPLICATION_URL = "application_url"
    COMPENSATION = "compensation"
    PAYMENT_REQUEST = "payment_request"
    CREDENTIAL_REQUEST = "credential_request"


class ExtractionStatus(str, Enum):
    EXTRACTED = "EXTRACTED"          # read from the document with a source quote
    UNCERTAIN = "UNCERTAIN"          # extractor is unsure; UI must ask the user to confirm
    USER_CONFIRMED = "USER_CONFIRMED"  # user accepted the extracted value unchanged
    USER_EDITED = "USER_EDITED"      # user replaced the value; no longer a document quote
    MISSING = "MISSING"              # expected field not present in the document


class SourceKind(str, Enum):
    DOCUMENT = "DOCUMENT"            # observation inside the uploaded offer itself
    SEARCH_SNIPPET = "SEARCH_SNIPPET"  # search-engine snippet; page itself not opened
    CHECKED_PAGE = "CHECKED_PAGE"    # the page was fetched and the quote found on it


class RetrievalStatus(str, Enum):
    LIVE = "LIVE"
    CACHED = "CACHED"
    DEMO = "DEMO"
    FAILED = "FAILED"


class SourceTier(str, Enum):
    OFFICIAL_EMPLOYER = "OFFICIAL_EMPLOYER"    # resolved official employer domain
    GOVERNMENT = "GOVERNMENT"                  # government / regulator source
    ESTABLISHED_THIRD_PARTY = "ESTABLISHED_THIRD_PARTY"  # major job board, news outlet
    USER_GENERATED = "USER_GENERATED"          # forums, social posts, reviews
    OFFER_DOCUMENT = "OFFER_DOCUMENT"          # the uploaded letter (a claim, not proof)
    UNKNOWN = "UNKNOWN"


class EvidenceRelation(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT = "CONTEXT"


class ClaimStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNRESOLVED = "UNRESOLVED"
    NOT_CHECKED = "NOT_CHECKED"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class EventStatus(str, Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


# ------------------------------------------------------------------- case input


class ConfirmedClaim(_ContractModel):
    """A value the user confirmed or corrected on the extraction screen."""

    claim_id: str
    kind: ClaimKind
    value: str
    extraction_status: ExtractionStatus

    @field_validator("extraction_status")
    @classmethod
    def _must_be_user_decision(cls, v: ExtractionStatus) -> ExtractionStatus:
        if v not in (ExtractionStatus.USER_CONFIRMED, ExtractionStatus.USER_EDITED):
            raise ValueError("confirmed_claims carry only USER_CONFIRMED or USER_EDITED values")
        return v


class CaseInput(_ContractModel):
    """What the run service hands to ``investigate_case``.

    ``redacted_text`` is the only document text that may reach search queries or
    hosted models; raw input stays inside the run service.
    """

    contract_version: str = CONTRACT_VERSION
    case_id: int
    run_id: str
    source_type: SourceType
    redacted_text: str
    confirmed_claims: List[ConfirmedClaim] = Field(default_factory=list)
    demo_mode: bool = False


# ------------------------------------------------------------- claims & evidence


class Claim(_ContractModel):
    claim_id: str
    kind: ClaimKind
    value: Optional[str] = None
    source_quote: Optional[str] = Field(
        None, description="Exact span from the document; null for MISSING or USER_EDITED values"
    )
    start_offset: Optional[int] = Field(None, ge=0)
    end_offset: Optional[int] = Field(None, ge=0)
    page: Optional[int] = Field(None, ge=1)
    extraction_status: ExtractionStatus

    @model_validator(mode="after")
    def _consistent(self) -> "Claim":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be given together")
        if self.start_offset is not None and self.end_offset < self.start_offset:
            raise ValueError("end_offset must be >= start_offset")
        if self.extraction_status == ExtractionStatus.EXTRACTED and not self.source_quote:
            raise ValueError("an EXTRACTED claim needs the source_quote it came from")
        if self.extraction_status == ExtractionStatus.MISSING and self.value is not None:
            raise ValueError("a MISSING claim has no value")
        return self


class EvidenceRecord(_ContractModel):
    evidence_id: str
    claim_id: str
    source_kind: SourceKind
    source_url: Optional[str] = Field(
        None, description="Null for document-local observations. Never a generic homepage used as filler."
    )
    title: str
    quote_or_snippet: str
    retrieved_at: datetime
    query: Optional[str] = None
    engine: Optional[str] = None
    search_id: Optional[str] = None
    retrieval_status: RetrievalStatus
    source_tier: SourceTier
    relation: EvidenceRelation

    @model_validator(mode="after")
    def _consistent(self) -> "EvidenceRecord":
        if self.source_kind == SourceKind.DOCUMENT:
            if self.source_tier != SourceTier.OFFER_DOCUMENT:
                raise ValueError("DOCUMENT evidence must use source_tier OFFER_DOCUMENT")
        elif not self.source_url and self.retrieval_status != RetrievalStatus.FAILED:
            raise ValueError("retrieved evidence needs a source_url")
        if self.source_kind == SourceKind.SEARCH_SNIPPET and (not self.query or not self.engine):
            raise ValueError("SEARCH_SNIPPET evidence must record the query and engine used")
        if self.retrieval_status == RetrievalStatus.FAILED and self.relation != EvidenceRelation.CONTEXT:
            raise ValueError("a FAILED retrieval cannot support or contradict a claim")
        if self.source_url and "api_key=" in self.source_url.lower():
            raise ValueError("provider keys must never appear in persisted URLs")
        return self


class AssessedClaim(_ContractModel):
    claim_id: str
    status: ClaimStatus
    explanation: str
    evidence_ids: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)


class Coverage(_ContractModel):
    """Completeness of the investigation — not a fraud probability."""

    checked_claims: int = Field(..., ge=0)
    total_claims: int = Field(..., ge=0)
    unresolved_claims: int = Field(..., ge=0)
    failed_checks: int = Field(..., ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> "Coverage":
        if self.checked_claims > self.total_claims:
            raise ValueError("checked_claims cannot exceed total_claims")
        if self.unresolved_claims > self.total_claims:
            raise ValueError("unresolved_claims cannot exceed total_claims")
        return self


class ConfirmationRoute(_ContractModel):
    """Independent, employer-published channel the student can use to confirm the offer."""

    channel: str = Field(..., description="e.g. careers_portal, official_email, official_phone")
    destination: str
    evidence_id: str = Field(..., description="Evidence showing the employer publishes this route")
    draft_message: Optional[str] = None


class ToolCall(_ContractModel):
    step: str
    tool: str
    query: Optional[str] = None
    reason: str = Field(..., description="Why the planner made this call")
    status: EventStatus
    started_at: datetime
    duration_ms: Optional[int] = Field(None, ge=0)
    evidence_ids: List[str] = Field(default_factory=list)


class RunError(_ContractModel):
    code: str
    message: str
    step: Optional[str] = None
    retryable: bool = False


class InvestigationResult(_ContractModel):
    contract_version: str = CONTRACT_VERSION
    run_id: str
    demo_mode: bool = False
    claims: List[Claim]
    assessed_claims: List[AssessedClaim]
    evidence: List[EvidenceRecord]
    overall_outcome: OverallOutcome
    authenticity_status: AuthenticityStatus = AuthenticityStatus.UNCONFIRMED
    coverage: Coverage
    recommended_actions: List[str] = Field(default_factory=list)
    confirmation_route: Optional[ConfirmationRoute] = None
    tool_trace: List[ToolCall] = Field(default_factory=list)
    errors: List[RunError] = Field(default_factory=list)

    @model_validator(mode="after")
    def _referential_integrity(self) -> "InvestigationResult":
        claim_ids = [c.claim_id for c in self.claims]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim_id values must be unique")
        evidence_by_id = {e.evidence_id: e for e in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("evidence_id values must be unique")

        for ev in self.evidence:
            if ev.claim_id not in claim_ids:
                raise ValueError(f"evidence {ev.evidence_id} references unknown claim {ev.claim_id}")
            if ev.retrieval_status == RetrievalStatus.DEMO and not self.demo_mode:
                raise ValueError("DEMO evidence is only allowed when demo_mode is true")

        assessed_ids = [a.claim_id for a in self.assessed_claims]
        if len(set(assessed_ids)) != len(assessed_ids):
            raise ValueError("each claim is assessed at most once")
        for a in self.assessed_claims:
            if a.claim_id not in claim_ids:
                raise ValueError(f"assessment references unknown claim {a.claim_id}")
            for eid in a.evidence_ids:
                ev = evidence_by_id.get(eid)
                if ev is None:
                    raise ValueError(f"assessment of {a.claim_id} cites unknown evidence {eid}")
                if ev.claim_id != a.claim_id:
                    raise ValueError(f"evidence {eid} belongs to {ev.claim_id}, not {a.claim_id}")
            relations = {evidence_by_id[eid].relation for eid in a.evidence_ids}
            if a.status == ClaimStatus.SUPPORTED and EvidenceRelation.SUPPORTS not in relations:
                raise ValueError(f"SUPPORTED claim {a.claim_id} needs supporting evidence")
            if a.status == ClaimStatus.CONTRADICTED and EvidenceRelation.CONTRADICTS not in relations:
                raise ValueError(f"CONTRADICTED claim {a.claim_id} needs contradicting evidence")

        for call in self.tool_trace:
            for eid in call.evidence_ids:
                if eid not in evidence_by_id:
                    raise ValueError(f"tool_trace step {call.step} cites unknown evidence {eid}")

        if self.confirmation_route and self.confirmation_route.evidence_id not in evidence_by_id:
            raise ValueError("confirmation_route must cite evidence retrieved in this run")

        if self.coverage.total_claims != len(self.claims):
            raise ValueError("coverage.total_claims must equal the number of claims")
        return self


# ------------------------------------------------------------------ run service


class RunEvent(_ContractModel):
    run_id: str
    sequence: int = Field(..., ge=0)
    step: str
    status: EventStatus
    public_message: str
    timestamp: datetime

    @field_validator("public_message")
    @classmethod
    def _no_secrets(cls, v: str) -> str:
        lowered = v.lower()
        if "api_key" in lowered or "apikey" in lowered:
            raise ValueError("public_message must not contain provider keys")
        return v


class RunSnapshot(_ContractModel):
    contract_version: str = CONTRACT_VERSION
    run_id: str
    case_id: int
    version: int = Field(..., ge=1, description="Report version for this case; force_refresh increments it")
    previous_run_id: Optional[str] = None
    status: RunStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    events: List[RunEvent] = Field(default_factory=list)
    report: Optional[InvestigationResult] = None
    errors: List[RunError] = Field(default_factory=list)

    @model_validator(mode="after")
    def _status_rules(self) -> "RunSnapshot":
        finished = self.status in (RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED)
        if self.status in (RunStatus.COMPLETED, RunStatus.PARTIAL) and self.report is None:
            raise ValueError(f"a {self.status.value} run must carry its report")
        if self.status in (RunStatus.QUEUED, RunStatus.RUNNING) and self.report is not None:
            raise ValueError("an unfinished run has no report yet")
        if self.status == RunStatus.FAILED and not self.errors:
            raise ValueError("a FAILED run must say why in errors")
        if finished and self.finished_at is None:
            raise ValueError("a finished run needs finished_at")
        if self.report is not None and self.report.run_id != self.run_id:
            raise ValueError("report.run_id must match the snapshot run_id")
        seqs = [e.sequence for e in self.events]
        if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
            raise ValueError("events must be in strictly increasing sequence order")
        if any(e.run_id != self.run_id for e in self.events):
            raise ValueError("all events must belong to this run")
        return self


class ErrorResponse(_ContractModel):
    """Error body for every non-2xx response (FastAPI's standard shape)."""

    detail: str
