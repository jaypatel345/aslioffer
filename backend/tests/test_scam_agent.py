import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.agents.scam_agent import ScamAgent
from app.services.search.serpapi_client import SerpApiClient, SearchSource


@pytest.mark.asyncio
async def test_registration_fee_triggers_high_risk():
    """Verify demanding a registration fee triggers HIGH_RISK, scam_flagged=True, and advance fee evidence."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(
        return_value={
            "source": SearchSource.REAL.value,
            "organic_results": [],
        }
    )

    agent = ScamAgent(search_client=mock_search)
    finding = await agent.investigate(
        company_name="Apex Global Tech",
        demanded_fee="INR 2,500 Registration Fee",
        payment_method="Bank Transfer",
        flags=["DEMANDS_UPFRONT_FEE"],
        raw_text="Please submit INR 2,500 registration fee before your final technical interview.",
    )

    assert finding.agent_name == "ScamAgent"
    assert finding.verdict == "HIGH_RISK"
    assert finding.confidence == 0.98
    assert finding.details["scam_flagged"] is True
    assert "UPFRONT_FEE_DEMAND" in finding.details["risk_signals"]
    assert any("Advance Fee" in ev.title for ev in finding.evidence)
    assert any("cybercrime.gov.in" in ev.source_url for ev in finding.evidence)


@pytest.mark.asyncio
async def test_upi_payment_verdict_bug_fixed():
    """Verify payment_method=UPI never returns VERIFIED even when fee is unspecified."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(
        return_value={
            "source": SearchSource.REAL.value,
            "organic_results": [],
        }
    )

    agent = ScamAgent(search_client=mock_search)
    finding = await agent.investigate(
        company_name="Innovate Corp",
        demanded_fee=None,
        payment_method="UPI",
        flags=[],
        raw_text="Send your security clearance charges via UPI to hr@okaxis.",
    )

    # CRITICAL: Must not return VERIFIED
    assert finding.verdict == "HIGH_RISK"
    assert finding.verdict != "VERIFIED"
    assert finding.details["scam_flagged"] is True
    assert "UPI_PAYMENT_REQUEST" in finding.details["risk_signals"]
    assert any("UPI Payment Request" in ev.title for ev in finding.evidence)


@pytest.mark.asyncio
async def test_telegram_recruiter_triggers_high_risk():
    """Verify Telegram task communication channel triggers HIGH_RISK and CyberDost advisory."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(
        return_value={
            "source": SearchSource.REAL.value,
            "organic_results": [],
        }
    )

    agent = ScamAgent(search_client=mock_search)
    finding = await agent.investigate(
        company_name="Media Solutions",
        demanded_fee=None,
        payment_method=None,
        flags=[],
        raw_text="Join our Telegram group @parttime_media_tasks to receive daily review assignments.",
    )

    assert finding.verdict == "HIGH_RISK"
    assert "TELEGRAM_COMMUNICATION" in finding.details["risk_signals"]
    assert any("Telegram Recruitment Fraud" in ev.title for ev in finding.evidence)


@pytest.mark.asyncio
async def test_clean_offer_returns_verified():
    """Verify legitimate offer without fees or scam indicators returns VERIFIED."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(
        return_value={
            "source": SearchSource.REAL.value,
            "organic_results": [],
        }
    )

    agent = ScamAgent(search_client=mock_search)
    finding = await agent.investigate(
        company_name="Infosys Limited",
        demanded_fee=None,
        payment_method=None,
        flags=[],
        raw_text="We are pleased to offer you the role of Systems Engineer. No fees are charged at any stage.",
    )

    assert finding.verdict == "VERIFIED"
    assert finding.confidence == 0.90
    assert finding.details["scam_flagged"] is False
    assert len(finding.details["risk_signals"]) == 0
    assert any("No Upfront Fee" in ev.title for ev in finding.evidence)


@pytest.mark.asyncio
async def test_search_failure_resilience():
    """Verify agent still flags HIGH_RISK on scam signals even when SerpApi search raises exceptions."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(side_effect=Exception("SerpApi network timeout / credit exhausted"))

    agent = ScamAgent(search_client=mock_search)
    finding = await agent.investigate(
        company_name="Shady Consulting",
        demanded_fee="Laptop deposit ₹10,000",
        payment_method="GPay",
        flags=["DEMANDS_UPFRONT_FEE"],
        raw_text="Transfer laptop deposit via GPay immediately.",
    )

    # Search failure must NOT prevent scam detection
    assert finding.verdict == "HIGH_RISK"
    assert finding.details["scam_flagged"] is True
    assert "UPFRONT_FEE_DEMAND" in finding.details["risk_signals"]
    assert "UPI_PAYMENT_REQUEST" in finding.details["risk_signals"]
    assert len(finding.evidence) >= 2


@pytest.mark.asyncio
async def test_mock_search_source_propagation():
    """Verify mock search results are converted to EvidenceItems and source is tracked."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(
        return_value={
            "source": SearchSource.MOCK.value,
            "organic_results": [
                {
                    "title": "Warning: Fraudulent job offers misusing TechCorp name",
                    "link": "https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                    "snippet": "Beware of fake recruitment requiring security deposits.",
                }
            ],
        }
    )

    agent = ScamAgent(search_client=mock_search)
    finding = await agent.investigate(
        company_name="TechCorp",
        demanded_fee="Security Deposit ₹5,000",
        payment_method=None,
        flags=[],
        raw_text="Mandatory refundable security deposit required before joining.",
    )

    assert finding.verdict == "HIGH_RISK"
    assert finding.details["search_source"] == SearchSource.MOCK.value
    # Search result added to evidence
    assert any("Warning: Fraudulent" in ev.title for ev in finding.evidence)


@pytest.mark.asyncio
async def test_independent_risk_signals_matrix():
    """Verify training fee, onboarding fee, whatsapp, and personal enterprise email all trigger HIGH_RISK."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(return_value={"source": SearchSource.REAL.value, "organic_results": []})
    agent = ScamAgent(search_client=mock_search)

    # 1. Training fee
    f1 = await agent.investigate("Enterprise Inc", None, None, [], "Candidates must pay training fee of 3000.")
    assert f1.verdict == "HIGH_RISK"

    # 2. Document verification fee
    f2 = await agent.investigate("Enterprise Inc", None, None, [], "Document verification fee is required.")
    assert f2.verdict == "HIGH_RISK"

    # 3. WhatsApp task group
    f3 = await agent.investigate("Enterprise Inc", None, None, [], "All communication will be through whatsapp task group.")
    assert f3.verdict == "HIGH_RISK"

    # 4. Personal email domain for enterprise claim
    f4 = await agent.investigate("Tata Consultancy Services", None, None, [], "Contact recruiter at tcs.recruitment@gmail.com")
    assert f4.verdict == "HIGH_RISK"
