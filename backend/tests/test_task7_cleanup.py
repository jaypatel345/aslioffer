"""Task 7 review regressions: privacy, grounding, ambiguity and corrections."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pydantic import ValidationError
from app.schemas.analysis import ExtractedData
from app.services.extractor.entity_extractor import EntityExtractor
from app.services.extractor.claim_models import Claim, ExtractionResult


def extractor():
    gemini = MagicMock(); gemini.api_key = "test"
    groq = MagicMock(); groq.api_key = "test"
    gemini.extract_entities = AsyncMock(return_value=ExtractedData())
    gemini.extract_from_document = AsyncMock()
    groq.extract_from_document = AsyncMock()
    return EntityExtractor(gemini, groq)


def test_secrets_and_candidate_contact_absent_from_complete_result():
    result = extractor().extract_claims("To: candidate@gmail.com\nFrom: hr@acme.com\nOTP: 123456\nPassword: Secret77\nOffer from Acme Corp.")
    serialized = result.model_dump_json()
    for secret in ("123456", "Secret77", "candidate@gmail.com"):
        assert secret not in serialized
    assert result.raw_text is None
    assert result.redacted_text == result.sanitized_source_buffer
    for claim in result.claims:
        if claim.source_span:
            span = claim.source_span
            assert span.target_text == "redacted_text"
            assert result.redacted_text[span.start_offset:span.end_offset] == claim.source_quote


@pytest.mark.asyncio
async def test_model_path_cannot_override_contact_roles_or_invent_salary():
    service = extractor()
    service.gemini_client.extract_entities.return_value = ExtractedData(
        company="Acme Corp", recruiter_email="candidate@gmail.com", salary="INR 99 LPA",
        website="https://invented.example", raw_text="OTP: 123456")
    text = "To: candidate@gmail.com\nFrom: hr@acme.com\nOffer from Acme Corp. Salary INR 7 LPA."
    result = await service.extract_claims_async(text)
    legacy = result.to_extracted_data()
    assert legacy.recruiter_email == "hr@acme.com"
    assert legacy.salary_amount == 7
    assert legacy.website is None
    assert any(w.code == "MODEL_PROPOSAL_REJECTED" for w in result.warnings)
    sent = service.gemini_client.extract_entities.call_args.args[0]
    assert "candidate@gmail.com" not in sent


@pytest.mark.asyncio
async def test_model_error_never_logs_document_or_secret(caplog):
    service = extractor()
    service.gemini_client.extract_entities.side_effect = RuntimeError("password: Secret77")
    result = await service.extract_claims_async("Offer from Acme Corp.")
    assert any(w.code == "MODEL_EXTRACTION_UNAVAILABLE" for w in result.warnings)
    assert "Secret77" not in result.model_dump_json() + caplog.text


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg", "application/pdf"])
@pytest.mark.asyncio
async def test_supported_binary_never_automatically_sent_to_vision(mime):
    service = extractor()
    with patch.object(service, "_extract_pdf_text_local", return_value=""):
        result = await service.extract_from_document(b"private binary", mime)
    service.gemini_client.extract_from_document.assert_not_awaited()
    service.groq_client.extract_from_document.assert_not_awaited()
    assert result["ocr_text"] == ""
    assert result["processing_status"] == "LOCAL_READING_UNAVAILABLE"


@pytest.mark.asyncio
async def test_short_local_pdf_text_is_accepted_and_sanitized():
    service = extractor()
    with patch.object(service, "_extract_pdf_text_local", return_value="OTP: 123456"):
        result = await service.extract_from_document(b"pdf", "application/pdf")
    assert result["ocr_text"]
    assert "123456" not in result["ocr_text"]
    service.gemini_client.extract_from_document.assert_not_awaited()


@pytest.mark.parametrize("text", [
    "Reply to hr1@acme.com or hr2@acme.com.",
    "Contact HR: +91 9876543210 or +91 9123456780.",
])
def test_adapter_does_not_choose_between_distinct_recruiter_contacts(text):
    result = extractor().extract_claims(text)
    data = result.to_extracted_data()
    assert data.recruiter_email is None
    assert data.recruiter_phone is None


def test_adapter_does_not_choose_ambiguous_employer():
    result = extractor().extract_claims("Acme Corp and Beta Limited are mentioned in this offer.")
    assert result.to_extracted_data().company is None


def test_mailbox_name_alone_does_not_establish_recruiter_role():
    result = extractor().extract_claims("An address mentioned: hr@acme.com")
    assert result.to_extracted_data().recruiter_email is None


def test_header_context_does_not_leak_to_unrelated_contact():
    result = extractor().extract_claims("From: hr@acme.com\nUnattributed address: jane@gmail.com")
    unknown = next(c for c in result.claims if c.value == "jane@gmail.com")
    assert unknown.kind == "contact"


@pytest.mark.parametrize("text,period,currency", [
    ("Stipend INR 15000 per month", "MONTHLY", "INR"),
    ("CTC INR 750000 per annum", "ANNUAL", "INR"),
    ("Salary INR 7 lakhs", None, "INR"),
    ("Salary $4000 per month", "MONTHLY", None),
])
def test_currency_and_period_are_explicit(text, period, currency):
    result = extractor().extract_claims(text)
    comp = next(c for c in result.claims if c.kind == "compensation")
    assert comp.attributes["period"] == period
    assert comp.attributes["currency"] == currency


def test_arbitrary_url_is_not_official_website():
    result = extractor().extract_claims("Read the article https://news.example/meet.google.com/story")
    assert result.to_extracted_data().website is None
    assert not any(c.kind == "interview_url" for c in result.claims)


@pytest.mark.parametrize("timestamp", ["not-a-date", "2026-10-04T10:00:00"])
def test_invalid_correction_timestamp_rejected(timestamp):
    result = extractor().extract_claims("Offer from Acme Corp.")
    target = next(c for c in result.claims if c.kind == "claimed_employer")
    with pytest.raises(ValueError):
        result.apply_user_correction(target.claim_id, "value", "Acme", timestamp)


def test_timezone_correction_reaches_adapter_and_preserves_original():
    result = extractor().extract_claims("Offer from Acme Corp.")
    target = next(c for c in result.claims if c.kind == "claimed_employer")
    result.apply_user_correction(target.claim_id, "value", "Corrected Employer", "2026-10-04T01:00:00-05:00")
    assert target.value == "Acme Corp"
    assert result.to_extracted_data().company == "Corrected Employer"
    with pytest.raises(ValueError):
        result.apply_user_correction(target.claim_id, "source_span", {})


@pytest.mark.parametrize("claims,ambiguities", [
    ([Claim(claim_id="same", kind="contact"), Claim(claim_id="same", kind="contact")], []),
    ([Claim(claim_id="one", kind="contact", source_quote="invented")], []),
    ([], [{"claim_id": "missing", "field": "value", "issue": "unknown"}]),
])
def test_invalid_result_provenance_rejected(claims, ambiguities):
    with pytest.raises(ValidationError):
        ExtractionResult(sanitized_source_buffer="real source", claims=claims, unresolved_ambiguities=ambiguities)


def test_credential_categories_do_not_invent_password_request():
    result = extractor().extract_claims("Share your bank OTP with HR.")
    cred = next(c for c in result.claims if c.kind == "credential_request")
    assert cred.attributes["credential_categories"] == ["bank_otp"]


def test_recognizable_candidate_ids_not_sent_or_retained():
    result = extractor().extract_claims("PAN: ABCDE1234F\nAadhaar: 1234 5678 9012")
    assert "ABCDE1234F" not in result.model_dump_json()
    assert "1234 5678 9012" not in result.model_dump_json()


def test_explicit_foreign_currency_not_relabelled_as_inr():
    result = extractor().extract_claims("Salary USD 4000 per month")
    comp = next(c for c in result.claims if c.kind == "compensation")
    assert comp.attributes["currency"] == "USD"
    assert comp.attributes["amount"] == 4000


def test_malformed_url_is_warning_not_extraction_crash():
    result = extractor().extract_claims("Website: https://[broken")
    assert any(w.code == "INVALID_URL" for w in result.warnings)
