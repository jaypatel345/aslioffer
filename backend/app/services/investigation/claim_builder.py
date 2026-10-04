"""
Claim builder and adapter for AsliOffer investigation pipeline (Task 10).

Builds grounded contract Claim records from redacted_text extraction,
preserves semantic contact roles, validates offsets against the input buffer,
and applies confirmed_claims explicitly with duplicate-ID rejection.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.contract import (
    CaseInput,
    Claim,
    ClaimKind,
    ConfirmedClaim,
    ExtractionStatus,
)
from app.services.extractor.claim_models import (
    ClaimKind as ExtractorClaimKind,
    ExtractionResult,
)
from app.services.extractor.entity_extractor import EntityExtractor
from app.services.agents.scam_classifier import (
    ScamClassifier,
    ScamModality,
    ScamSignalCode,
    SignalAssessment,
)


REDACTION_PLACEHOLDERS = {
    "[email_1]",
    "[email_2]",
    "[phone_1]",
    "[phone_2]",
    "[upi_id_1]",
    "[upi_id_2]",
    "[company_1]",
    "[employer_1]",
    "[candidate_name_1]",
    "[candidate_email]",
    "[redacted_candidate_email]",
    "[redacted_id]",
    "unknown company",
    "unknown employer",
}


def is_redaction_placeholder(val: Optional[str]) -> bool:
    """Returns True if the value is a known redaction placeholder or bracketed token."""
    if not val or not isinstance(val, str):
        return False
    clean = val.strip().lower()
    if clean in REDACTION_PLACEHOLDERS:
        return True
    if clean.startswith("[") and clean.endswith("]"):
        return True
    return False


def validate_offsets(text: str, quote: Optional[str], start: Optional[int], end: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    """
    Validates that [start:end] slices text into quote exactly.
    Returns (start, end) if valid; otherwise (None, None).
    """
    if start is None or end is None or not quote or not text:
        return None, None
    if not (0 <= start <= end <= len(text)):
        return None, None
    if text[start:end] != quote:
        return None, None
    return start, end


class ClaimBuilder:
    """
    Constructs contract Claim records for an investigation run.
    """

    def __init__(self, extractor: Optional[EntityExtractor] = None, scam_classifier: Optional[ScamClassifier] = None):
        self.extractor = extractor or EntityExtractor()
        self.scam_classifier = scam_classifier or ScamClassifier()

    def build_claims(self, case_input: CaseInput) -> Tuple[List[Claim], List[SignalAssessment], ExtractionResult]:
        """
        Extracts document claims, merges confirmed_claims, and validates provenance.
        """
        # 1. Validate confirmed_claims for duplicate IDs
        seen_confirmed_ids: Set[str] = set()
        for cc in case_input.confirmed_claims:
            if cc.claim_id in seen_confirmed_ids:
                raise ValueError(f"Duplicate confirmed claim ID '{cc.claim_id}' in case_input")
            seen_confirmed_ids.add(cc.claim_id)

        # 2. Extract grounded claims from redacted_text
        text = case_input.redacted_text or ""
        ext_result = self.extractor.extract_claims(text, source_type=case_input.source_type.value)
        data = ext_result.to_extracted_data()

        # 3. Classify scam and contextual signals
        scam_assessments = self.scam_classifier.classify(
            raw_text=text,
            demanded_fee=data.payment_amount,
            payment_method=data.payment_method,
            flags=data.flags,
        )

        active_fee_demands = [
            a for a in scam_assessments
            if a.modality == ScamModality.ACTIVE_DEMAND and a.signal_code in (
                ScamSignalCode.UPFRONT_FEE_DEMAND,
                ScamSignalCode.UNLOCK_PAYMENT_DEMAND,
                ScamSignalCode.UPI_PAYMENT_REQUEST,
            )
        ]
        active_cred_demands = [
            a for a in scam_assessments
            if a.modality == ScamModality.ACTIVE_DEMAND and a.signal_code == ScamSignalCode.CREDENTIAL_THEFT_DEMAND
        ]

        # 4. Map extractor claims to dictionary of candidates by kind
        # Note: Semantic separation of contact roles:
        # candidate contacts (CANDIDATE_CONTACT) must NOT become recruiter contacts!
        extracted_by_kind: Dict[ClaimKind, List[Dict[str, Any]]] = {}

        # Company / Employer
        company_val = data.company
        company_quote = None
        company_span = None
        for c in ext_result.claims:
            if c.kind == ExtractorClaimKind.CLAIMED_EMPLOYER.value and c.value:
                company_val = str(c.value)
                company_quote = c.source_quote
                company_span = c.source_span
                break

        if company_val and not is_redaction_placeholder(company_val):
            extracted_by_kind.setdefault(ClaimKind.EMPLOYER, []).append({
                "value": company_val,
                "source_quote": company_quote or company_val if company_val in text else None,
                "start": company_span.start_offset if company_span else (text.find(company_val) if company_val in text else None),
                "end": company_span.end_offset if company_span else (text.find(company_val) + len(company_val) if company_val in text else None),
                "status": ExtractionStatus.EXTRACTED,
            })
        else:
            extracted_by_kind.setdefault(ClaimKind.EMPLOYER, []).append({
                "value": None,
                "source_quote": None,
                "start": None,
                "end": None,
                "status": ExtractionStatus.MISSING,
            })

        # Sender email (Recruiter contact only)
        recruiter_email = data.recruiter_email
        email_quote = None
        email_span = None
        for c in ext_result.claims:
            if c.kind == ExtractorClaimKind.CANDIDATE_CONTACT.value:
                # Explicitly ignore candidate contacts
                continue
            if c.kind in (ExtractorClaimKind.CONTACT.value, ExtractorClaimKind.SENDER_RECRUITER.value):
                val = str(c.value or "")
                if "@" in val and not is_redaction_placeholder(val):
                    recruiter_email = val
                    email_quote = c.source_quote
                    email_span = c.source_span
                    break

        if recruiter_email:
            start_off = email_span.start_offset if email_span else (text.find(recruiter_email) if recruiter_email in text else None)
            end_off = email_span.end_offset if email_span else (text.find(recruiter_email) + len(recruiter_email) if recruiter_email in text else None)
            extracted_by_kind.setdefault(ClaimKind.SENDER_EMAIL, []).append({
                "value": recruiter_email,
                "source_quote": email_quote or recruiter_email if recruiter_email in text else None,
                "start": start_off,
                "end": end_off,
                "status": ExtractionStatus.EXTRACTED,
            })

        # Contact phone (Recruiter phone only)
        recruiter_phone = data.recruiter_phone
        if recruiter_phone:
            extracted_by_kind.setdefault(ClaimKind.CONTACT_PHONE, []).append({
                "value": recruiter_phone,
                "source_quote": recruiter_phone if recruiter_phone in text else None,
                "start": text.find(recruiter_phone) if recruiter_phone in text else None,
                "end": text.find(recruiter_phone) + len(recruiter_phone) if recruiter_phone in text else None,
                "status": ExtractionStatus.EXTRACTED,
            })

        # Recruiter name
        recruiter_name = data.recruiter_name
        if recruiter_name and not is_redaction_placeholder(recruiter_name):
            extracted_by_kind.setdefault(ClaimKind.RECRUITER_NAME, []).append({
                "value": recruiter_name,
                "source_quote": recruiter_name if recruiter_name in text else None,
                "start": text.find(recruiter_name) if recruiter_name in text else None,
                "end": text.find(recruiter_name) + len(recruiter_name) if recruiter_name in text else None,
                "status": ExtractionStatus.EXTRACTED,
            })

        # Application URL / destination
        for c in ext_result.claims:
            if c.kind in (ExtractorClaimKind.APPLICATION_DESTINATION.value, ExtractorClaimKind.INTERVIEW_URL.value):
                if c.value:
                    val = str(c.value)
                    extracted_by_kind.setdefault(ClaimKind.APPLICATION_URL, []).append({
                        "value": val,
                        "source_quote": c.source_quote or (val if val in text else None),
                        "start": c.source_span.start_offset if c.source_span else (text.find(val) if val in text else None),
                        "end": c.source_span.end_offset if c.source_span else (text.find(val) + len(val) if val in text else None),
                        "status": ExtractionStatus.EXTRACTED,
                    })
                    break

        # Role
        role = data.job_role
        role_quote = None
        role_span = None
        for c in ext_result.claims:
            if c.kind == ExtractorClaimKind.JOB_ROLE.value and c.value:
                role = str(c.value)
                role_quote = c.source_quote
                role_span = c.source_span
                break

        if role and not is_redaction_placeholder(role):
            extracted_by_kind.setdefault(ClaimKind.ROLE, []).append({
                "value": role,
                "source_quote": role_quote or (role if role in text else None),
                "start": role_span.start_offset if role_span else (text.find(role) if role in text else None),
                "end": role_span.end_offset if role_span else (text.find(role) + len(role) if role in text else None),
                "status": ExtractionStatus.EXTRACTED,
            })

        # Location / Address
        if data.address and not is_redaction_placeholder(data.address):
            extracted_by_kind.setdefault(ClaimKind.LOCATION, []).append({
                "value": data.address,
                "source_quote": data.address if data.address in text else None,
                "start": text.find(data.address) if data.address in text else None,
                "end": text.find(data.address) + len(data.address) if data.address in text else None,
                "status": ExtractionStatus.EXTRACTED,
            })

        # Job Reference ID
        for c in ext_result.claims:
            if c.kind == ExtractorClaimKind.JOB_REFERENCE_ID.value and c.value:
                ref_val = str(c.value)
                extracted_by_kind.setdefault(ClaimKind.JOB_REFERENCE, []).append({
                    "value": ref_val,
                    "source_quote": c.source_quote or (ref_val if ref_val in text else None),
                    "start": c.source_span.start_offset if c.source_span else (text.find(ref_val) if ref_val in text else None),
                    "end": c.source_span.end_offset if c.source_span else (text.find(ref_val) + len(ref_val) if ref_val in text else None),
                    "status": ExtractionStatus.EXTRACTED,
                })
                break

        # Compensation
        if data.salary:
            extracted_by_kind.setdefault(ClaimKind.COMPENSATION, []).append({
                "value": data.salary,
                "source_quote": data.salary if data.salary in text else None,
                "start": text.find(data.salary) if data.salary in text else None,
                "end": text.find(data.salary) + len(data.salary) if data.salary in text else None,
                "status": ExtractionStatus.EXTRACTED,
            })

        # Payment Request (Essential claim)
        if active_fee_demands:
            primary_demand = active_fee_demands[0]
            val = primary_demand.source_quote or data.payment_amount or "Upfront payment demand detected"
            quote = primary_demand.source_quote
            span = primary_demand.source_span or {}
            start = span.get("start") or span.get("start_offset") or (text.find(quote) if quote and quote in text else None)
            end = span.get("end") or span.get("end_offset") or ((start + len(quote)) if start is not None and quote else None)
            extracted_by_kind.setdefault(ClaimKind.PAYMENT_REQUEST, []).append({
                "value": val,
                "source_quote": quote,
                "start": start,
                "end": end,
                "status": ExtractionStatus.EXTRACTED,
            })
        elif data.payment_request_detected:
            extracted_by_kind.setdefault(ClaimKind.PAYMENT_REQUEST, []).append({
                "value": data.payment_amount or "Payment request detected",
                "source_quote": data.payment_amount if data.payment_amount and data.payment_amount in text else None,
                "start": text.find(data.payment_amount) if data.payment_amount and data.payment_amount in text else None,
                "end": text.find(data.payment_amount) + len(data.payment_amount) if data.payment_amount and data.payment_amount in text else None,
                "status": ExtractionStatus.EXTRACTED,
            })
        else:
            extracted_by_kind.setdefault(ClaimKind.PAYMENT_REQUEST, []).append({
                "value": None,
                "source_quote": None,
                "start": None,
                "end": None,
                "status": ExtractionStatus.MISSING,
            })

        # Credential Request
        if active_cred_demands:
            primary_cred = active_cred_demands[0]
            cquote = primary_cred.source_quote
            cspan = primary_cred.source_span or {}
            cstart = cspan.get("start") or cspan.get("start_offset") or (text.find(cquote) if cquote and cquote in text else None)
            cend = cspan.get("end") or cspan.get("end_offset") or ((cstart + len(cquote)) if cstart is not None and cquote else None)
            extracted_by_kind.setdefault(ClaimKind.CREDENTIAL_REQUEST, []).append({
                "value": cquote or "Sensitive credential demand",
                "source_quote": cquote,
                "start": cstart,
                "end": cend,
                "status": ExtractionStatus.EXTRACTED,
            })

        # 5. Order claims canonically and assign deterministic IDs
        canonical_order = [
            ClaimKind.EMPLOYER,
            ClaimKind.SENDER_EMAIL,
            ClaimKind.CONTACT_PHONE,
            ClaimKind.RECRUITER_NAME,
            ClaimKind.APPLICATION_URL,
            ClaimKind.ROLE,
            ClaimKind.LOCATION,
            ClaimKind.JOB_REFERENCE,
            ClaimKind.COMPENSATION,
            ClaimKind.PAYMENT_REQUEST,
            ClaimKind.CREDENTIAL_REQUEST,
        ]

        # Check if confirmed_claims specifies explicit claim IDs for matching kinds
        confirmed_by_id = {cc.claim_id: cc for cc in case_input.confirmed_claims}
        confirmed_by_kind = {cc.kind: cc for cc in case_input.confirmed_claims}

        initial_claims: List[Dict[str, Any]] = []
        for kind in canonical_order:
            if kind in extracted_by_kind:
                for item in extracted_by_kind[kind]:
                    initial_claims.append({
                        "kind": kind,
                        **item,
                    })

        # Assign deterministic claim IDs
        # If confirmed_claims has specific claim_id mappings, preserve them
        claims: List[Claim] = []
        claim_index = 1
        used_ids: Set[str] = set()

        for cdict in initial_claims:
            kind = cdict["kind"]
            # Look up if user confirmed this kind with an explicit ID
            cc = confirmed_by_kind.get(kind)
            claim_id = cc.claim_id if (cc and cc.claim_id not in used_ids) else f"c{claim_index}"
            while claim_id in used_ids:
                claim_index += 1
                claim_id = f"c{claim_index}"

            used_ids.add(claim_id)
            claim_index += 1

            val = cdict["value"]
            quote = cdict["source_quote"]
            s_off, e_off = validate_offsets(text, quote, cdict["start"], cdict["end"])
            status = cdict["status"]

            # Apply user confirmation/editing if matching cc found
            if cc and cc.claim_id == claim_id:
                if cc.extraction_status == ExtractionStatus.USER_EDITED:
                    val = cc.value
                    quote = None
                    s_off = None
                    e_off = None
                    status = ExtractionStatus.USER_EDITED
                elif cc.extraction_status == ExtractionStatus.USER_CONFIRMED:
                    val = cc.value
                    status = ExtractionStatus.USER_CONFIRMED

            # Model validation guarantees
            if status == ExtractionStatus.EXTRACTED and not quote:
                # If EXTRACTED but quote is missing, either set quote to value or downgrade to UNCERTAIN
                if val and val in text:
                    quote = val
                    s_off, e_off = validate_offsets(text, quote, text.find(val), text.find(val) + len(val))
                else:
                    status = ExtractionStatus.UNCERTAIN

            if status == ExtractionStatus.MISSING:
                val = None
                quote = None
                s_off = None
                e_off = None

            claims.append(
                Claim(
                    claim_id=claim_id,
                    kind=kind,
                    value=val,
                    source_quote=quote,
                    start_offset=s_off,
                    end_offset=e_off,
                    page=None,
                    extraction_status=status,
                )
            )

        # Include any confirmed_claims that were not present in initial extracted claims
        for cc in case_input.confirmed_claims:
            if cc.claim_id not in used_ids:
                used_ids.add(cc.claim_id)
                claims.append(
                    Claim(
                        claim_id=cc.claim_id,
                        kind=cc.kind,
                        value=cc.value,
                        source_quote=None,
                        start_offset=None,
                        end_offset=None,
                        page=None,
                        extraction_status=cc.extraction_status,
                    )
                )

        return claims, scam_assessments, ext_result
