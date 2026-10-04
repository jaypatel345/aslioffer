"""
Offline evaluation corpus loader and definitions for AsliOffer (Task 13).

Defines the EvaluationCase data structure and provides deterministic loading
and serialization for the 27 offline evaluation cases covering all required scenarios:
- Explicit upfront payment demands
- Credential or OTP demands
- Plausible employer impersonation
- Lookalike application destinations
- Legitimate recruitment with corroborated public records
- Authorized recruitment agencies
- Small employers with sparse public footprints
- Negated payment demands and quoted scam warnings
- Candidate/recruiter contact separation
- Matching vacancies that do not authenticate individual offers
- Different role seniority and specializations
- Closed or expired vacancies
- Exact versus partial requisition matches
- Private offer references
- Associated versus unestablished ATS tenants
- Independently published confirmation contacts
- Submitted-only or negatively described contacts
- Empty successful searches
- Provider failure
- Search-budget exhaustion
- Investigation deadlines
- Strong warnings surviving vacancy corroboration
"""

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.schemas.contract import (
    CaseInput,
    ClaimKind,
    ClaimStatus,
    ConfirmedClaim,
    ExtractionStatus,
    OverallOutcome,
    SourceType,
    CONTRACT_VERSION,
)
from app.services.investigation.budget import InvestigationBudget

CORPUS_DATA_DIR = Path(__file__).resolve().parent / "data"


class CaseInputSpec(BaseModel):
    case_id: int
    run_id: str
    source_type: SourceType = SourceType.TEXT
    redacted_text: str
    confirmed_claims: List[ConfirmedClaim] = Field(default_factory=list)
    demo_mode: bool = False

    def to_case_input(self) -> CaseInput:
        return CaseInput(
            contract_version=CONTRACT_VERSION,
            case_id=self.case_id,
            run_id=self.run_id,
            source_type=self.source_type,
            redacted_text=self.redacted_text,
            confirmed_claims=self.confirmed_claims,
            demo_mode=self.demo_mode,
        )


class BudgetSpec(BaseModel):
    max_search_calls: int = 8
    max_followup_calls: int = 3
    max_concurrent_calls: int = 3
    deadline_seconds: float = 15.0

    def to_investigation_budget(self) -> InvestigationBudget:
        return InvestigationBudget(
            max_search_calls=self.max_search_calls,
            max_followup_calls=self.max_followup_calls,
            max_concurrent_calls=self.max_concurrent_calls,
            deadline_seconds=self.deadline_seconds,
        )


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    title: str
    description: str
    labels: Dict[str, Any] = Field(default_factory=dict)
    case_input: CaseInputSpec
    budget: Optional[BudgetSpec] = None
    search_mock: Dict[str, Any] = Field(default_factory=dict)
    expected_outcome: str
    allowed_outcomes: List[str] = Field(default_factory=list)
    expected_claim_statuses: Dict[str, str] = Field(default_factory=dict)
    required_behaviors: List[str] = Field(default_factory=list)
    forbidden_behaviors: List[str] = Field(default_factory=list)
    planted_secrets: List[str] = Field(default_factory=list)
    rationale: str
    expectations: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('expected_outcome')
    @classmethod
    def valid_outcome(cls, value):
        OverallOutcome(value)
        return value

    @field_validator('allowed_outcomes')
    @classmethod
    def valid_allowed_outcomes(cls, values):
        for value in values:
            OverallOutcome(value)
        return values

    @field_validator('expected_claim_statuses')
    @classmethod
    def valid_claim_expectations(cls, values):
        for kind, status in values.items():
            ClaimKind(kind)
            ClaimStatus(status)
        return values

    def get_allowed_outcomes(self) -> List[str]:
        if self.allowed_outcomes:
            return self.allowed_outcomes
        return [self.expected_outcome]


def get_default_corpus_cases() -> List[EvaluationCase]:
    """The committed JSON corpus is the single source of truth; never write on load."""
    return load_evaluation_corpus()


def save_evaluation_corpus(cases: List[EvaluationCase], target_dir: Optional[Path] = None) -> List[Path]:
    """Writes all evaluation cases to separate JSON files in target_dir."""
    dest = target_dir or CORPUS_DATA_DIR
    dest.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    for c in cases:
        file_path = dest / f"{c.case_id.lower().replace('-', '_')}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(c.model_dump_json(indent=2))
        saved_paths.append(file_path)
    return saved_paths


def load_evaluation_corpus(source_dir: Optional[Path] = None) -> List[EvaluationCase]:
    """Fail closed on missing, malformed, empty or duplicate-ID corpus data."""
    src = source_dir or CORPUS_DATA_DIR
    paths = sorted(src.glob("eval_*.json")) if src.is_dir() else []
    if not paths:
        raise ValueError(f"No evaluation cases found in {src}")
    cases = []
    ids = set()
    for path in paths:
        try:
            case = EvaluationCase.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Invalid evaluation case: {path.name} ({type(exc).__name__})") from None
        if case.case_id in ids:
            raise ValueError(f"Duplicate evaluation case ID: {case.case_id}")
        ids.add(case.case_id)
        cases.append(case)
    return cases
