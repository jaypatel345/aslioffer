"""
Comprehensive offline implementation tests for Task 7:
Grounded, role-aware entity extraction in AsliOffer.
"""

import json
from unittest.mock import AsyncMock, patch
import pytest

from app.services.extractor.claim_models import (
    ClaimKind,
    ConfidenceTier,
    ExtractionResult,
    ExtractionStatus,
)
from app.services.extractor.grounded_parser import GroundedParser
from app.services.extractor.entity_extractor import EntityExtractor
from app.schemas.analysis import ExtractedData


@pytest.fixture
def parser():
    return GroundedParser()


@pytest.fixture
def extractor():
    return EntityExtractor()


# ---------------------------------------------------------------------------
# 1. Contact Role Attribution
# ---------------------------------------------------------------------------


def test_contact_roles_candidate_first(parser):
    """Candidate email appears first in To/greeting, recruiter email in From/signature."""
    text = (
        "To: candidate.john@gmail.com\n"
        "From: talent.acquisition@infosys.com\n"
        "Dear John, we are pleased to offer you the Software Engineer role.\n"
        "Regards, Anita Roy, HR Infosys"
    )
    result = parser.parse(text)

    cand_claim = next(c for c in result.claims if c.value == "candidate.john@gmail.com")
    rec_claim = next(c for c in result.claims if c.value == "talent.acquisition@infosys.com")

    assert cand_claim.kind == ClaimKind.CANDIDATE_CONTACT.value
    assert cand_claim.attributes.get("semantic_role") == "candidate_destination"

    assert rec_claim.kind == ClaimKind.SENDER_RECRUITER.value
    assert rec_claim.attributes.get("semantic_role") == "sender_contact"

    # Adapter check: recruiter_email must be the sender, never candidate
    data = result.to_extracted_data()
    assert data.recruiter_email == "talent.acquisition@infosys.com"


def test_contact_roles_recruiter_first(parser):
    """Recruiter contact appears first in header/body."""
    text = (
        "From: hr.recruiter@wipro.com\n"
        "To: rahul.sharma@yahoo.com\n"
        "Congratulations Rahul! Contact me at +91 9876543210.\n"
        "Best regards,\nRahul Verma (HR)"
    )
    result = parser.parse(text)

    rec_claim = next(c for c in result.claims if c.value == "hr.recruiter@wipro.com")
    assert rec_claim.kind == ClaimKind.SENDER_RECRUITER.value
    assert rec_claim.attributes.get("semantic_role") == "sender_contact"

    phone_claim = next(c for c in result.claims if c.attributes.get("channel") == "phone")
    assert phone_claim.kind == ClaimKind.SENDER_RECRUITER.value
    assert phone_claim.attributes.get("semantic_role") == "sender_contact"


def test_contact_roles_unknown(parser):
    """Unattributed email without sender/candidate cues stays unknown."""
    text = "For general technical inquiries, contact support@thirdparty.org."
    result = parser.parse(text)

    email_claims = [c for c in result.claims if c.value == "support@thirdparty.org"]
    assert len(email_claims) == 1
    assert email_claims[0].kind == ClaimKind.CONTACT.value
    assert email_claims[0].attributes.get("semantic_role") == "unknown"

    # Legacy adapter must not promote unknown email to recruiter
    data = result.to_extracted_data()
    assert data.recruiter_email is None


def test_multiple_recruiter_candidates_produces_ambiguity(parser):
    """Multiple plausible recruiter contacts without clear single sender creates ambiguity."""
    text = (
        "Offer from Tech Mahindra.\n"
        "Please send your reply to hr.team1@techmahindra.com or hr.team2@techmahindra.com."
    )
    result = parser.parse(text)

    rec_claims = [c for c in result.claims if c.kind == ClaimKind.SENDER_RECRUITER.value]
    assert len(rec_claims) == 2

    # Ambiguity should be recorded because there are multiple recruiter candidates
    amb = [a for a in result.unresolved_ambiguities if a.field == "sender_recruiter"]
    assert len(amb) >= 1


# ---------------------------------------------------------------------------
# 2. Employer vs Meeting Tool vs Agency
# ---------------------------------------------------------------------------


def test_real_google_employer_vs_meeting_tool(parser):
    """Google as real employer vs Google Meet as meeting tool."""
    # Scenario A: Meeting tool
    tool_text = "Interview scheduled via Google Meet for Software Engineer at V-Guard Industries."
    res_tool = parser.parse(tool_text)

    emp_claims = [c for c in res_tool.claims if c.kind == ClaimKind.CLAIMED_EMPLOYER.value and c.value]
    assert len(emp_claims) == 1
    assert "V-Guard" in emp_claims[0].value

    tool_claims = [c for c in res_tool.claims if c.kind == ClaimKind.MEETING_PLATFORM.value]
    assert len(tool_claims) >= 1
    assert "Google Meet" in tool_claims[0].value

    # Scenario B: Google is genuine employer
    google_text = "Welcome to Google LLC. We are pleased to offer you the role of Software Engineer at Google India."
    res_google = parser.parse(google_text)

    google_emp = [c for c in res_google.claims if c.kind == ClaimKind.CLAIMED_EMPLOYER.value and c.value and "Google" in c.value]
    assert len(google_emp) >= 1


def test_agency_and_client_distinction(parser):
    """Staffing agency hiring on behalf of client employer."""
    text = "Apex Staffing Solutions is hiring on behalf of client Infosys Limited for Software Engineer."
    result = parser.parse(text)

    agency = next(c for c in result.claims if c.kind == ClaimKind.RECRUITING_AGENCY.value)
    client = next(c for c in result.claims if c.kind == ClaimKind.CLAIMED_EMPLOYER.value)

    assert "Apex" in agency.value
    assert agency.attributes.get("role") == "staffing_agency"

    assert "Infosys" in client.value
    assert client.attributes.get("role") == "client_employer"

    # Adapter check: company should prefer client_employer
    data = result.to_extracted_data()
    assert "Infosys" in data.company


def test_ambiguous_employer_claims(parser):
    """Multiple competing employers produce ambiguity."""
    text = "Joint appointment: You will be employed by Alpha Services and Beta Technologies."
    result = parser.parse(text)

    emp_amb = [
        a for a in result.unresolved_ambiguities
        if any(c.kind == ClaimKind.CLAIMED_EMPLOYER.value for c in result.claims if c.claim_id == a.claim_id)
        or a.field == "value"
    ]
    assert len(emp_amb) >= 2


# ---------------------------------------------------------------------------
# 3. Compensation: Base Units, Ranges, and Ambiguities
# ---------------------------------------------------------------------------


def test_salary_base_units_and_lpa_conversion(parser):
    """7.2 LPA converted to base currency units (720,000 INR) with legacy LPA adapter."""
    text = "Offered Package: INR 7.2 LPA for Software Engineer."
    result = parser.parse(text)

    comp = next(c for c in result.claims if c.kind == ClaimKind.COMPENSATION.value)
    assert comp.attributes.get("amount") == 720000.0
    assert comp.attributes.get("currency") == "INR"
    assert comp.attributes.get("period") == "ANNUAL"

    # Legacy adapter keeps LPA magnitude
    data = result.to_extracted_data()
    assert data.salary_amount == 7.2
    assert data.salary_period == "LPA"


def test_salary_range(parser):
    """Salary range parsed with min/max base units."""
    text = "Monthly stipend: INR 25,000 - 35,000 per month."
    result = parser.parse(text)

    comp = next(c for c in result.claims if c.kind == ClaimKind.COMPENSATION.value)
    assert comp.attributes.get("amount") == 25000.0
    assert comp.attributes.get("amount_range") == [25000.0, 35000.0]
    assert comp.attributes.get("period") == "MONTHLY"


def test_salary_ctc_period_ambiguity(parser):
    """Unspecified CTC frequency flagged as AMBIGUOUS without guessing annual."""
    text = "Total CTC: INR 750000."
    result = parser.parse(text)

    comp = next(c for c in result.claims if c.kind == ClaimKind.COMPENSATION.value)
    assert comp.extraction_status == ExtractionStatus.AMBIGUOUS.value
    assert comp.attributes.get("period") is None

    amb = [a for a in result.unresolved_ambiguities if a.field == "period"]
    assert len(amb) >= 1
    assert "period" in amb[0].issue.lower() or "frequency" in amb[0].issue.lower()


def test_stipend_unspecified_frequency_ambiguity(parser):
    """Stipend without frequency flagged as AMBIGUOUS without guessing monthly."""
    text = "Internship Stipend: INR 15000."
    result = parser.parse(text)

    comp = next(c for c in result.claims if c.kind == ClaimKind.COMPENSATION.value)
    assert comp.extraction_status == ExtractionStatus.AMBIGUOUS.value
    assert comp.attributes.get("period") is None


# ---------------------------------------------------------------------------
# 4. Location and Missing Fields (No Fabricated Defaults)
# ---------------------------------------------------------------------------


def test_missing_location_no_defaults(parser):
    """Text without location leaves location null, never inventing 'Remote / India'."""
    text = "Congratulations on your selection at TCS. Contact hr@tcs.com."
    result = parser.parse(text)

    loc_claims = [c for c in result.claims if c.kind == ClaimKind.LOCATION.value]
    assert len(loc_claims) == 0

    data = result.to_extracted_data()
    assert data.address is None

    entities = data.to_extracted_entities()
    assert entities.location is None


# ---------------------------------------------------------------------------
# 5. URL Purpose Classification
# ---------------------------------------------------------------------------


def test_url_purpose_separation(parser):
    """Distinguish meeting URLs, application URLs, and official websites."""
    text = (
        "Visit our company portal at https://www.infosys.com.\n"
        "Submit documents at https://careers.infosys.com/apply.\n"
        "Join technical round at https://meet.google.com/abc-defg-hij."
    )
    result = parser.parse(text)

    url_claims = [
        c for c in result.claims
        if c.kind in [
            ClaimKind.INTERVIEW_URL.value,
            ClaimKind.APPLICATION_DESTINATION.value,
            ClaimKind.OFFICIAL_DOMAIN_REFERENCE.value,
        ]
    ]
    assert len(url_claims) >= 3

    meet_claim = next(c for c in url_claims if "meet.google.com" in c.value)
    assert meet_claim.kind == ClaimKind.INTERVIEW_URL.value
    assert meet_claim.attributes.get("purpose") == "interview_platform"

    apply_claim = next(c for c in url_claims if "careers.infosys.com" in c.value)
    assert apply_claim.kind == ClaimKind.APPLICATION_DESTINATION.value
    assert apply_claim.attributes.get("purpose") == "application_destination"

    official_claim = next(c for c in url_claims if "www.infosys.com" in c.value)
    assert official_claim.kind == ClaimKind.OFFICIAL_DOMAIN_REFERENCE.value
    assert official_claim.attributes.get("purpose") == "official_website"

    # Legacy adapter should point website to official website, not Google Meet
    data = result.to_extracted_data()
    assert data.website == "https://www.infosys.com"


# ---------------------------------------------------------------------------
# 6. Payment & Credential Context (Active vs Negated vs Policies)
# ---------------------------------------------------------------------------


def test_active_payment_demand(parser):
    """Active payment demand produces active claim and legacy flags."""
    text = "Pay refundable security deposit of INR 5000 via UPI to account hr@upi before joining."
    result = parser.parse(text)

    pay_claims = [c for c in result.claims if c.kind == ClaimKind.PAYMENT_REQUEST.value]
    assert len(pay_claims) >= 1
    assert pay_claims[0].attributes.get("is_active_demand") is True
    assert pay_claims[0].attributes.get("payment_method") == "UPI"

    data = result.to_extracted_data()
    assert data.payment_request_detected is True
    assert "DEMANDS_UPFRONT_FEE" in data.flags


def test_negated_payment_policy(parser):
    """Company policy stating they never ask for money does NOT produce active demand."""
    text = (
        "Offer from Wipro Limited.\n"
        "IMPORTANT NOTICE: Wipro does not charge any registration fee, security deposit or training fee."
    )
    result = parser.parse(text)

    active_pay = [
        c for c in result.claims
        if c.kind == ClaimKind.PAYMENT_REQUEST.value and c.attributes.get("is_active_demand") is True
    ]
    assert len(active_pay) == 0

    data = result.to_extracted_data()
    assert data.payment_request_detected is False
    assert "DEMANDS_UPFRONT_FEE" not in data.flags


def test_quoted_payment_warning(parser):
    """Quoted scam warning does NOT produce an active payment demand."""
    text = "Advisory: Beware of fraudsters asking candidates for ₹2500 laptop deposit via Google Pay."
    result = parser.parse(text)

    active_pay = [
        c for c in result.claims
        if c.kind == ClaimKind.PAYMENT_REQUEST.value and c.attributes.get("is_active_demand") is True
    ]
    assert len(active_pay) == 0

    data = result.to_extracted_data()
    assert data.payment_request_detected is False


def test_ordinary_onboarding_id_vs_credential_theft(parser):
    """Standard onboarding ID verification distinguished from credential theft."""
    # Standard onboarding ID
    id_text = "Please submit copies of your PAN card and Aadhaar card for employee verification."
    res_id = parser.parse(id_text)

    cred_claims = [c for c in res_id.claims if c.kind == ClaimKind.CREDENTIAL_REQUEST.value]
    assert len(cred_claims) >= 1
    assert cred_claims[0].attributes.get("credential_categories") == ["identity_document"]
    assert cred_claims[0].attributes.get("requested_action") == "request_identity_document"

    # Credential theft
    theft_text = "Please share your NetBanking password and debit card PIN immediately."
    res_theft = parser.parse(theft_text)
    theft_claims = [c for c in res_theft.claims if c.kind == ClaimKind.CREDENTIAL_REQUEST.value]
    assert len(theft_claims) >= 1
    assert theft_claims[0].attributes.get("is_active_demand") is True


# ---------------------------------------------------------------------------
# 7. Secret Redaction and Unicode Span Verification
# ---------------------------------------------------------------------------


def test_secret_redaction(parser):
    """Live OTPs and passwords are fully redacted from source buffer and claims."""
    text = "Your verification OTP is 482910. Your temporary password is MySecretPass123!."
    result = parser.parse(text)

    assert "482910" not in result.sanitized_source_buffer
    assert "MySecretPass123!" not in result.sanitized_source_buffer
    assert "[REDACTED_SECRET]" in result.sanitized_source_buffer

    # Verify no claim contains the raw secret
    for c in result.claims:
        assert "482910" not in str(c.value)
        assert "MySecretPass123!" not in str(c.value)


def test_unicode_span_exact_match(parser):
    """Source spans strictly match Unicode code points in the sanitized buffer."""
    text = "🚀 Congratulations! Offer from Infosys for Software Engineer. Package ₹8.5 LPA. 🎉"
    result = parser.parse(text)

    for c in result.claims:
        if c.source_span and c.source_quote:
            start = c.source_span.start_offset
            end = c.source_span.end_offset
            assert result.sanitized_source_buffer[start:end] == c.source_quote


# ---------------------------------------------------------------------------
# 8. User Corrections
# ---------------------------------------------------------------------------


def test_user_corrections_preserving_evidence(parser):
    """User correction adds attributable correction without overwriting raw evidence."""
    text = "Offer from Tech Corp for Developer role."
    result = parser.parse(text)

    emp_claim = next(c for c in result.claims if c.kind == ClaimKind.CLAIMED_EMPLOYER.value)
    original_id = emp_claim.claim_id
    original_val = emp_claim.value

    # Apply correction
    corr_claim = result.apply_user_correction(
        target_claim_id=original_id,
        corrected_field="value",
        corrected_value="Tech Corporation Global",
    )

    assert corr_claim.kind == ClaimKind.USER_CORRECTION.value
    assert corr_claim.attributes.get("target_claim_id") == original_id

    # Verify original claim is preserved
    unaltered_emp = next(c for c in result.claims if c.claim_id == original_id)
    assert unaltered_emp.value == original_val

    # Effective claims must reflect correction
    effective = result.get_effective_claims()
    eff_emp = next(c for c in effective if c.claim_id == original_id)
    assert eff_emp.value == "Tech Corporation Global"
    assert eff_emp.extraction_status == ExtractionStatus.USER_CORRECTED.value


# ---------------------------------------------------------------------------
# 9. Unsupported Documents and Model Fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_binary_document_no_vision_call(extractor):
    """Binary garbage returns unsupported warning and never calls external vision."""
    opaque_binary = b"\x00\x01\x02\x03\x04\xff\xfe\xfd\x80" * 20

    with patch.object(extractor.gemini_client, "extract_from_document", new_callable=AsyncMock) as mock_gemini:
        with patch.object(extractor.groq_client, "extract_from_document", new_callable=AsyncMock) as mock_groq:
            res = await extractor.extract_from_document(
                file_bytes=opaque_binary,
                mime_type="application/octet-stream",
            )

            # Neither external vision client should be called
            mock_gemini.assert_not_called()
            mock_groq.assert_not_called()

            assert res.get("ocr_text") == ""


@pytest.mark.asyncio
async def test_model_hallucination_rejected(extractor):
    """Hallucinated employer from AI model is rejected in favor of grounded document text."""
    doc_text = "Welcome to Tata Consultancy Services. Offer for Software Engineer. Package ₹6 LPA."

    # Model hallucinates "Google LLC" which is not in doc_text
    mock_model_data = ExtractedData(
        company="Google LLC",
        job_role="Software Engineer",
        salary="₹6 LPA",
        salary_amount=6.0,
        salary_period="LPA",
        raw_text=doc_text,
    )

    with patch.object(extractor.gemini_client, "extract_entities", new_callable=AsyncMock, return_value=mock_model_data):
        data = await extractor.extract_entities(doc_text)

        # Grounded employer must be TCS, not Google
        assert data.company == "Tata Consultancy Services"
