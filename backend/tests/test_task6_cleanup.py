"""Offline regressions for Task 6 review; no provider or extraction changes."""
import json
from unittest.mock import AsyncMock
import pytest
from app.services.agents.scam_agent import ScamAgent
from app.services.agents.scam_classifier import ScamClassifier, sanitize_and_redact_secrets


def client():
    c = AsyncMock()
    c.search.return_value = {"source": "REAL", "organic_results": []}
    return c


@pytest.mark.parametrize("text", [
    "Join our WhatsApp task group for assignments.",
    "Telegram webinar announcements are available.",
    "Send your CV to jobs@acme.com.",
    "UPI ID is shown in our payroll instructions.",
    "We use OTP and password authentication.",
    "Your salary will be credited via UPI.",
    "Unlock your earnings dashboard to view your wages.",
])
@pytest.mark.asyncio
async def test_ordinary_mentions_do_not_raise_risk(text):
    finding = await ScamAgent(client()).investigate("Acme", None, None, [], text)
    assert finding.verdict == "VERIFIED"
    assert not finding.details["risk_signals"]


@pytest.mark.parametrize("text", [
    "We never charge registration fees; pay the laptop deposit before joining.",
    "We never charge registration fees but pay the mandatory security deposit.",
    "Do not share your OTP and please share your account password with HR.",
    'Security advisory: avoid fake offers. Recruiter says "pay the registration fee before joining".',
    "Enter the OTP on the official portal yourself; share your bank OTP with HR.",
    "Please provide your password with HR.",
    "To withdraw earnings, recharge your wallet.",
])
@pytest.mark.asyncio
async def test_local_benign_context_cannot_suppress_real_demand(text):
    finding = await ScamAgent(client()).investigate("Acme", None, None, [], text)
    assert finding.verdict == "HIGH_RISK"
    assert finding.details["risk_signals"]


@pytest.mark.parametrize("text", ["Training fee schedule attached.", "Security deposit information is available."])
@pytest.mark.asyncio
async def test_fee_reference_is_ambiguous_not_active(text):
    finding = await ScamAgent(client()).investigate("Acme", None, None, [], text)
    assert finding.verdict == "NEEDS_REVIEW"
    assert not finding.details["risk_signals"]


@pytest.mark.asyncio
async def test_otp_policy_does_not_contradict_fee_hint():
    finding = await ScamAgent(client()).investigate("Acme", "registration fee", None, [], "Do not share your OTP.")
    assert finding.verdict == "NEEDS_REVIEW"


@pytest.mark.asyncio
async def test_salary_payment_rail_hint_is_not_uncorroborated_demand():
    finding = await ScamAgent(client()).investigate("Acme", None, "UPI", [], "Your salary will be credited through UPI.")
    assert finding.verdict == "VERIFIED"


@pytest.mark.parametrize("title,snippet", [
    ("Other Inc fake job complaint", "Victim paid a fee to Other Inc."),
    ("Acme official careers", "Welcome to our hiring page."),
    ("Acme security advisory", "Beware of fake job offers and do not pay fees."),
])
@pytest.mark.asyncio
async def test_unrelated_or_prevention_search_hits_are_not_scam_evidence(title, snippet):
    c = client(); c.search.return_value = {"source": "REAL", "organic_results": [{"title": title, "snippet": snippet, "link": "https://reports.example/page"}]}
    finding = await ScamAgent(c).investigate("Acme", "registration fee", None, [], "Pay the registration fee before joining.")
    assert all(e.source_url == "document://submitted-offer" for e in finding.evidence)


@pytest.mark.asyncio
async def test_secret_values_do_not_escape_through_structured_hints_or_searches():
    c = client()
    finding = await ScamAgent(c).investigate("Acme", "fee password: Secret77", "OTP: 123456", [], "Pay the mandatory registration fee and share your password Secret77 with HR.")
    payload = json.dumps(finding.model_dump())
    assert "Secret77" not in payload
    assert "123456" not in payload
    assert "Secret77" not in str(c.search.call_args_list)
    assert "123456" not in str(c.search.call_args_list)


def test_repeated_quote_does_not_get_wrong_occurrence_span():
    text = "Pay the registration fee. Pay the registration fee."
    sanitized = sanitize_and_redact_secrets(text)
    for a in ScamClassifier().classify(text):
        if a.source_span:
            assert sanitized[a.source_span["start_offset"]:a.source_span["end_offset"]] == a.source_quote


@pytest.mark.asyncio
async def test_otp_only_demand_does_not_claim_password_was_requested():
    finding = await ScamAgent(client()).investigate("Acme", None, None, [], "Share your bank OTP with HR.")
    assert finding.details["otp_requested"]
    assert not finding.details["password_requested"]

@pytest.mark.parametrize("text", ["Security deposit is not required.", "The employer will cover the training fee."])
@pytest.mark.asyncio
async def test_negated_or_employer_paid_fee_is_not_candidate_demand(text):
    finding = await ScamAgent(client()).investigate("Acme", None, None, [], text)
    assert finding.verdict == "VERIFIED"
    assert not finding.details["risk_signals"]
