"""
Claim-based extraction result models for AsliOffer (Task 7).

Implements the contract specification from docs/extraction-requirements.md (v1.0.1).
Extraction identifies document claims with grounded provenance, explicit ambiguity,
and secret-safe redaction.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.analysis import ExtractedData, ExtractedEntities


class ClaimKind(str, Enum):
    CLAIMED_EMPLOYER = "claimed_employer"
    CONTACT = "contact"
    JOB_REFERENCE_ID = "job_reference_id"
    JOINING_DATE = "joining_date"
    LOCATION = "location"
    RECRUITING_AGENCY = "recruiting_agency"
    SENDER_RECRUITER = "sender_recruiter"
    CANDIDATE_CONTACT = "candidate_contact"
    MEETING_PLATFORM = "meeting_platform"
    JOB_ROLE = "job_role"
    COMPENSATION = "compensation"
    PAYMENT_REQUEST = "payment_request"
    CREDENTIAL_REQUEST = "credential_request"
    INTERVIEW_URL = "interview_url"
    APPLICATION_DESTINATION = "application_destination"
    OFFICIAL_DOMAIN_REFERENCE = "official_domain_reference"
    USER_CORRECTION = "user_correction"


class ExtractionStatus(str, Enum):
    EXTRACTED = "extracted"
    USER_CORRECTED = "user_corrected"
    AMBIGUOUS = "ambiguous"
    ABSENT = "absent"


class ConfidenceTier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SourceSpan(BaseModel):
    start_offset: Optional[int] = Field(None, description="Unicode code point offset start (inclusive)")
    end_offset: Optional[int] = Field(None, description="Unicode code point offset end (exclusive)")
    target_text: str = Field("raw_text", description="Name of buffer containing span (raw_text, ocr_text, redacted_text)")
    page_number: Optional[int] = Field(None, description="Document page number if reliable OCR metadata exists")
    bounding_box: Optional[Dict[str, Any]] = Field(None, description="Bounding box if reliable OCR metadata exists")


class Claim(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    claim_id: str = Field(..., description="Unique claim identifier, e.g. CLM-01-01")
    kind: ClaimKind = Field(..., description="Semantic claim category")
    value: Optional[Any] = Field(None, description="Extracted claim value; null only when absent")
    source_quote: Optional[str] = Field(None, description="Exact substring of the identified sanitized buffer")
    source_span: Optional[SourceSpan] = Field(None, description="Verified offset coordinates within the buffer")
    extraction_status: ExtractionStatus = Field(ExtractionStatus.EXTRACTED.value, description="Extraction state")
    confidence_tier: Optional[ConfidenceTier] = Field(ConfidenceTier.HIGH.value, description="Extraction clarity tier (not fraud probability)")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Kind-specific claim attributes")


class UnresolvedAmbiguity(BaseModel):
    claim_id: str = Field(..., description="Reference to the ambiguous claim")
    field: str = Field(..., description="Specific ambiguous field/attribute")
    issue: str = Field(..., description="Human-readable description of the unresolved ambiguity")


class ExtractionWarning(BaseModel):
    code: str = Field(..., description="Machine-readable warning code")
    message: str = Field(..., description="Sanitized human-readable warning message")


class ExtractionResult(BaseModel):
    contract_version: str = Field("1.0.1", description="Contract version")
    source_type: str = Field("text", description="Source format: text, email, pdf, screenshot")
    extraction_method: str = Field("regex", description="Method: regex, model, ocr_model, hybrid, fallback")
    sanitized_source_buffer: str = Field("", description="The sanitized text buffer used for spans and quotes")
    raw_text: Optional[str] = Field(None, description="Input raw text")
    ocr_text: Optional[str] = Field(None, description="OCR text if extracted from document")
    redacted_text: Optional[str] = Field(None, description="Redacted buffer text")
    claims: List[Claim] = Field(default_factory=list, description="Extracted claims")
    unresolved_ambiguities: List[UnresolvedAmbiguity] = Field(default_factory=list, description="Unresolved ambiguities")
    warnings: List[ExtractionWarning] = Field(default_factory=list, description="Sanitized extraction warnings")

    @model_validator(mode="after")
    def validate_provenance(self):
        if self.raw_text is not None:
            raise ValueError("Raw input must not be retained in extraction results")
        ids = [c.claim_id for c in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("Claim IDs must be unique")
        for claim in self.claims:
            if claim.source_quote and claim.source_quote not in self.sanitized_source_buffer:
                raise ValueError("Quote is not grounded in the sanitized buffer")
            span = claim.source_span
            if span:
                start, end = span.start_offset, span.end_offset
                if (start is None or end is None or start < 0 or end <= start
                    or end > len(self.sanitized_source_buffer)
                    or span.target_text != "redacted_text"
                    or self.sanitized_source_buffer[start:end] != claim.source_quote):
                    raise ValueError("Invalid source span")
        if any(a.claim_id not in ids for a in self.unresolved_ambiguities):
            raise ValueError("Ambiguity target does not exist")
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Serializes result into contract-compliant dictionary."""
        return self.model_dump()

    def get_claims_by_kind(self, kind: Union[ClaimKind, str]) -> List[Claim]:
        kind_str = kind.value if isinstance(kind, ClaimKind) else str(kind)
        return [c for c in self.claims if c.kind == kind_str]

    def get_effective_claims(self) -> List[Claim]:
        """
        Computes effective claims incorporating any user_correction claims.
        Original claims remain unmodified in self.claims; this returns a copy
        reflecting the latest corrected values.
        """
        effective = {c.claim_id: c.model_copy(deep=True) for c in self.claims if c.kind != ClaimKind.USER_CORRECTION.value}
        corrections = [c for c in self.claims if c.kind == ClaimKind.USER_CORRECTION.value]

        for corr in corrections:
            target_id = corr.attributes.get("target_claim_id")
            field = corr.attributes.get("corrected_field")
            val = corr.attributes.get("corrected_value")
            if target_id and target_id in effective and field:
                target = effective[target_id]
                target.attributes[field] = val
                if field == "value":
                    target.value = val
                target.extraction_status = ExtractionStatus.USER_CORRECTED.value

        return list(effective.values())

    def apply_user_correction(
        self,
        target_claim_id: str,
        corrected_field: str,
        corrected_value: Any,
        timestamp: Optional[str] = None,
    ) -> Claim:
        """
        Attaches a user_correction claim targeting an existing claim attribute.
        Preserves original document evidence and clears corresponding unresolved ambiguity.
        """
        target = next((c for c in self.claims if c.claim_id == target_claim_id), None)
        if not target:
            raise ValueError(f"Target claim {target_claim_id} does not exist")
        if target.kind == ClaimKind.USER_CORRECTION.value:
            raise ValueError("Cannot target a user_correction claim with another correction")

        corr_id = f"CLM-99-{len(self.claims) + 1:02d}"
        if corrected_field != "value" and corrected_field not in target.attributes:
            raise ValueError("Correction field is not an attribute of the target")
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        parsed_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if parsed_ts.tzinfo is None:
            raise ValueError("Correction timestamp must include a timezone")
        from app.services.agents.scam_classifier import sanitize_and_redact_secrets
        def sanitize_value(value):
            if isinstance(value, str):
                return sanitize_and_redact_secrets(value)
            if isinstance(value, list):
                return [sanitize_value(v) for v in value]
            if isinstance(value, dict):
                return {sanitize_value(k): sanitize_value(v) for k, v in value.items()}
            return value
        corrected_value = sanitize_value(corrected_value)

        corr_claim = Claim(
            claim_id=corr_id,
            kind=ClaimKind.USER_CORRECTION.value,
            value=corrected_value,
            source_quote=None,
            source_span=None,
            extraction_status=ExtractionStatus.USER_CORRECTED.value,
            confidence_tier=ConfidenceTier.HIGH.value,
            attributes={
                "target_claim_id": target_claim_id,
                "corrected_field": corrected_field,
                "corrected_value": corrected_value,
                "resolved_ambiguities": [u.model_dump() for u in self.unresolved_ambiguities if u.claim_id == target_claim_id and u.field == corrected_field],
                "attribution": {
                    "source": "user_interactive_confirmation",
                    "timestamp": ts,
                    "target_claim_id": target_claim_id,
                },
            },
        )
        self.claims.append(corr_claim)

        # Clear matching unresolved ambiguity
        self.unresolved_ambiguities = [
            u for u in self.unresolved_ambiguities
            if not (u.claim_id == target_claim_id and u.field == corrected_field)
        ]

        return corr_claim

    def to_extracted_data(self) -> ExtractedData:
        """
        Adapter converting claim-based extraction result into legacy ExtractedData
        while strictly preserving Task 3-6 investigation behaviors.
        """
        effective_claims = self.get_effective_claims()
        # 1. Employer
        employer_claims = [c for c in effective_claims if c.kind == ClaimKind.CLAIMED_EMPLOYER.value and c.value]
        company = employer_claims[0].value if len(employer_claims) == 1 and employer_claims[0].extraction_status != "ambiguous" else None

        # 2. Recruiter
        recruiter_claims = [c for c in effective_claims if c.kind == ClaimKind.SENDER_RECRUITER.value and c.value]
        recruiter_email = None
        recruiter_phone = None
        recruiter_name = None

        for rc in recruiter_claims:
            if rc.extraction_status == "ambiguous":
                continue
            ch = rc.attributes.get("channel")
            if ch == "email" and not recruiter_email:
                recruiter_email = str(rc.value)
            elif ch == "phone" and not recruiter_phone:
                recruiter_phone = str(rc.value)
            if rc.attributes.get("recruiter_name") and not recruiter_name:
                recruiter_name = str(rc.attributes["recruiter_name"])

        # Check explicit contact claims if sender_recruiter wasn't found
        if not recruiter_email or not recruiter_phone:
            for cc in effective_claims:
                if cc.kind == ClaimKind.CONTACT.value and cc.extraction_status != "ambiguous":
                    ch = cc.attributes.get("channel")
                    role = cc.attributes.get("semantic_role")
                    if role in ("recruiter_contact", "sender_contact"):
                        if ch == "email" and not recruiter_email:
                            recruiter_email = str(cc.value)
                        elif ch == "phone" and not recruiter_phone:
                            recruiter_phone = str(cc.value)

        # 3. Job Role
        role_claims = [c for c in effective_claims if c.kind == ClaimKind.JOB_ROLE.value and c.value]
        job_role = role_claims[0].value if role_claims else None

        # 4. Compensation
        comp_claims = [c for c in effective_claims if c.kind == ClaimKind.COMPENSATION.value and c.value]
        salary_str = None
        salary_amount = None
        salary_period = None
        if comp_claims:
            c = comp_claims[0]
            salary_str = str(c.value)
            # Legacy conversion: preserve LPA magnitude as e.g. 7.2 or 8.0
            amt = c.attributes.get("amount")
            period = c.attributes.get("period")
            if period == "ANNUAL" and amt and amt >= 100000:
                salary_amount = float(amt) / 100000.0
                salary_period = "LPA"
            elif period == "MONTHLY":
                salary_amount = float(amt) if amt else None
                salary_period = "per month"
            elif period == "ANNUAL":
                salary_amount = float(amt) if amt else None
                salary_period = "per annum"
            else:
                salary_amount = float(amt) if amt else None
                salary_period = None

        # 5. Dates & Location
        date_claims = [c for c in effective_claims if c.kind == ClaimKind.JOINING_DATE.value and c.value]
        joining_date = date_claims[0].value if date_claims else None

        loc_claims = [c for c in effective_claims if c.kind == ClaimKind.LOCATION.value and c.value]
        address = loc_claims[0].value if loc_claims else None

        # 6. Official Website
        web_claims = [c for c in effective_claims if c.kind == ClaimKind.OFFICIAL_DOMAIN_REFERENCE.value and c.value]
        website = web_claims[0].value if web_claims else None

        # 7. Payment requests (active demands)
        active_payment_claims = [
            c for c in effective_claims
            if c.kind == ClaimKind.PAYMENT_REQUEST.value
            and c.attributes.get("is_active_demand") is True
        ]
        payment_request_detected = bool(active_payment_claims)
        payment_amount = None
        payment_method = None
        is_reg_fee = False

        if active_payment_claims:
            p_claim = active_payment_claims[0]
            payment_amount = str(p_claim.value) if p_claim.value else None
            payment_method = p_claim.attributes.get("payment_method")
            purpose = (p_claim.attributes.get("purpose") or "").lower()
            if "registration" in purpose:
                is_reg_fee = True

        # 8. Flags
        flags: List[str] = []
        if payment_request_detected:
            flags.append("DEMANDS_UPFRONT_FEE")
            if is_reg_fee:
                flags.append("REGISTRATION_FEE_REQUESTED")

        if payment_method and payment_method.upper() in ["UPI", "GPAY", "PHONEPE", "PAYTM"]:
            flags.append("UPI_PAYMENT_REQUESTED")

        # Recruiter webmail flag: ONLY if grounded recruiter_email uses public domain
        if recruiter_email:
            free_domains = ["gmail.com", "outlook.com", "yahoo.com", "hotmail.com"]
            domain = recruiter_email.split("@")[-1].lower() if "@" in recruiter_email else ""
            if domain in free_domains:
                flags.append("PUBLIC_EMAIL_DOMAIN_USED")

        buffer_text = self.sanitized_source_buffer or self.raw_text or ""

        return ExtractedData(
            company=company,
            recruiter_name=recruiter_name,
            recruiter_email=recruiter_email,
            recruiter_phone=recruiter_phone,
            job_role=job_role,
            salary=salary_str,
            salary_amount=salary_amount,
            salary_period=salary_period,
            joining_date=joining_date,
            address=address,
            website=website,
            payment_request_detected=payment_request_detected,
            payment_amount=payment_amount,
            payment_method=payment_method,
            flags=flags,
            raw_text=buffer_text,
        )

    def to_extracted_entities(self) -> ExtractedEntities:
        """Adapter converting result directly into ExtractedEntities."""
        return self.to_extracted_data().to_extracted_entities()
