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
    assert all(ev.source_url == "document://submitted-offer" for ev in finding.evidence)


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
async def test_telegram_channel_alone_is_needs_review_not_high_risk():
    """Verify Telegram communication channel alone without fee demands triggers NEEDS_REVIEW, not HIGH_RISK."""
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

    # Must NOT be marked HIGH_RISK when no active payment or credential demands exist
    assert finding.verdict != "HIGH_RISK"
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.details["scam_flagged"] is False
    assert any(a["signal_code"] == "TELEGRAM_COMMUNICATION" for a in finding.details["signal_assessments"])


@pytest.mark.asyncio
async def test_telegram_channel_with_active_fee_triggers_high_risk():
    """Verify Telegram group accompanied by an active upfront fee demand triggers HIGH_RISK."""
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
        demanded_fee="Registration Fee INR 1,500",
        payment_method="UPI",
        flags=["DEMANDS_UPFRONT_FEE"],
        raw_text="Join our Telegram group @parttime_media_tasks and transfer INR 1,500 registration fee via UPI.",
    )

    assert finding.verdict == "HIGH_RISK"
    assert finding.details["scam_flagged"] is True
    assert "UPFRONT_FEE_DEMAND" in finding.details["risk_signals"]


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
    assert finding.evidence == []
    assert finding.details["local_scan_completed"] is True


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
    """Synthetic search evidence is excluded while local warning signals survive."""
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
    # Synthetic provider results must not be cited as live evidence.
    assert not any("Warning: Fraudulent" in ev.title for ev in finding.evidence)
    assert all(ev.source_url == "document://submitted-offer" for ev in finding.evidence)


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

    # 4. Personal email domain alone is deferred to RecruiterAgent; ScamAgent does not force HIGH_RISK
    f4 = await agent.investigate("Tata Consultancy Services", None, None, [], "Contact recruiter at tcs.recruitment@gmail.com")
    assert f4.verdict != "HIGH_RISK"
    assert "PERSONAL_EMAIL_ENTERPRISE" not in f4.details.get("risk_signals", [])


# ===========================================================================
# Task 6 Contextual Scam Detection Offline Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_active_demand_vs_negated_policy():
    """Verify localized negation does not suppress an active demand in an adjacent clause."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(return_value={"source": SearchSource.REAL.value, "organic_results": []})
    agent = ScamAgent(search_client=mock_search)

    # Mixed clauses: negated registration fee + mandatory laptop deposit
    text = "We do not charge registration fees. Pay the mandatory laptop deposit of INR 5,000."
    finding = await agent.investigate("Tech Global", None, None, [], text)

    assert finding.verdict == "HIGH_RISK"
    assert "UPFRONT_FEE_DEMAND" in finding.details["risk_signals"]
    assert finding.details["fee_detected"] is True

    # Pure negated policy
    text_pure = "Our policy is transparent: We never charge any security deposit, registration fee, or onboarding deposit."
    finding_pure = await agent.investigate("Tech Global", None, None, [], text_pure)
    assert finding_pure.verdict == "VERIFIED"
    assert "UPFRONT_FEE_DEMAND" not in finding_pure.details["risk_signals"]
    assert finding_pure.details["negated_fee_found"] is True


@pytest.mark.asyncio
async def test_mixed_benign_and_malicious_clauses():
    """Verify benign clauses (benefits, work culture) do not obscure active extortion or fee demands."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(return_value={"source": SearchSource.REAL.value, "organic_results": []})
    agent = ScamAgent(search_client=mock_search)

    text = (
        "We offer comprehensive medical insurance, 24 days annual leave, and flexible hybrid hours. "
        "Candidates must transfer INR 3,000 document verification fee to HR before final offer issuance."
    )
    finding = await agent.investigate("Horizon Corp", None, None, [], text)

    assert finding.verdict == "HIGH_RISK"
    assert "UPFRONT_FEE_DEMAND" in finding.details["risk_signals"]


@pytest.mark.asyncio
async def test_forwarded_real_demand_vs_prevention_example():
    """Quotation marks alone must not suppress a forwarded demand, while explicitly quoted advisories are recognized."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(return_value={"source": SearchSource.REAL.value, "organic_results": []})
    agent = ScamAgent(search_client=mock_search)

    # Forwarded real demand inside quotes
    forwarded = 'The recruiter instructed: "Please transfer INR 4,000 security deposit via UPI to hr@okaxis immediately."'
    f_real = await agent.investigate("Apex Tech", None, None, [], forwarded)
    assert f_real.verdict == "HIGH_RISK"
    assert "UPFRONT_FEE_DEMAND" in f_real.details["risk_signals"]

    # Explicit quoted advisory / fraud prevention warning
    warning = 'Security Advisory for Applicants: Fraudsters are circulating fake letters stating "Pay INR 4,000 security deposit via UPI to confirm seat". Do not transfer funds.'
    f_advisory = await agent.investigate("Apex Tech", None, None, [], warning)
    assert f_advisory.verdict == "VERIFIED"
    assert "UPFRONT_FEE_DEMAND" not in f_advisory.details["risk_signals"]
    assert f_advisory.details["quoted_warning_detected"] is True


@pytest.mark.asyncio
async def test_payment_direction_salary_receipt_vs_candidate_payment():
    """Distinguish employer-to-candidate salary payments from candidate-to-recruiter payment demands."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(return_value={"source": SearchSource.REAL.value, "organic_results": []})
    agent = ScamAgent(search_client=mock_search)

    # Employer paying salary through bank transfer / UPI
    salary_text = "Your monthly salary of INR 65,000 will be credited through bank transfer on the last working day."
    f_salary = await agent.investigate("Global Services", None, "Bank Transfer", [], salary_text)
    assert f_salary.verdict == "VERIFIED"
    assert len(f_salary.details["risk_signals"]) == 0

    # Candidate paying recruiter
    payment_demand = "Transfer INR 2,500 registration charge via bank transfer to recruiter account."
    f_pay = await agent.investigate("Global Services", "INR 2,500", "Bank Transfer", [], payment_demand)
    assert f_pay.verdict == "HIGH_RISK"
    assert "UPFRONT_FEE_DEMAND" in f_pay.details["risk_signals"]


@pytest.mark.asyncio
async def test_generic_otp_verification_vs_credential_theft():
    """Distinguish official portal OTP verification from recruiter soliciting bank OTPs or passwords."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(return_value={"source": SearchSource.REAL.value, "organic_results": []})
    agent = ScamAgent(search_client=mock_search)

    # Legitimate self-service OTP direction
    self_service = "Enter the OTP on the official portal yourself to verify your email address."
    f_legit = await agent.investigate("SecureCorp", None, None, [], self_service)
    assert f_legit.verdict == "VERIFIED"
    assert "CREDENTIAL_THEFT_DEMAND" not in f_legit.details["risk_signals"]

    # Negated OTP sharing advice
    negated_otp = "Do not share your bank OTP or net-banking password with anyone claiming to represent HR."
    f_negated = await agent.investigate("SecureCorp", None, None, [], negated_otp)
    assert f_negated.verdict == "VERIFIED"
    assert "CREDENTIAL_THEFT_DEMAND" not in f_negated.details["risk_signals"]

    # Active credential theft
    theft = "Please share your bank OTP and net-banking password immediately with HR at verify@gmail.example to activate payroll."
    f_theft = await agent.investigate("SecureCorp", None, None, [], theft)
    assert f_theft.verdict == "HIGH_RISK"
    assert "CREDENTIAL_THEFT_DEMAND" in f_theft.details["risk_signals"]
    assert f_theft.details["otp_requested"] is True
    assert f_theft.details["password_requested"] is True


@pytest.mark.asyncio
async def test_structured_hints_contradicted_by_raw_text():
    """Structured fee hints contradicted by document text must not force HIGH_RISK."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(return_value={"source": SearchSource.REAL.value, "organic_results": []})
    agent = ScamAgent(search_client=mock_search)

    # Hint says fee demanded, but text clearly has negated policy
    raw_text = "Welcome to TCS. Policy Notice: We never charge a security deposit or registration fee at any stage."
    finding = await agent.investigate(
        company_name="Tata Consultancy Services",
        demanded_fee="INR 5,000",
        payment_method="UPI",
        flags=["DEMANDS_UPFRONT_FEE"],
        raw_text=raw_text,
    )

    assert finding.verdict == "VERIFIED"
    assert "UPFRONT_FEE_DEMAND" not in finding.details["risk_signals"]
    assert finding.details["negated_fee_found"] is True


@pytest.mark.asyncio
async def test_active_demands_with_missing_structured_fields():
    """Explicit raw-text demands must be detected even when structured fields are completely absent."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(return_value={"source": SearchSource.REAL.value, "organic_results": []})
    agent = ScamAgent(search_client=mock_search)

    # Missing demanded_fee, missing payment_method, empty flags
    raw_text = "To courier your company laptop, you must transfer a refundable security deposit of INR 4,500."
    finding = await agent.investigate(
        company_name="Cloud Tech",
        demanded_fee=None,
        payment_method=None,
        flags=[],
        raw_text=raw_text,
    )

    assert finding.verdict == "HIGH_RISK"
    assert "UPFRONT_FEE_DEMAND" in finding.details["risk_signals"]
    assert finding.details["scam_flagged"] is True


@pytest.mark.asyncio
async def test_provider_failures_and_demo_results():
    """Active local scam signals must survive search provider failures and demo mode."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(
        return_value={
            "source": SearchSource.MOCK.value,
            "status": "failed",
            "organic_results": [],
            "outcome": "PROVIDER_FAILURE",
        }
    )
    agent = ScamAgent(search_client=mock_search)

    raw_text = "Pay INR 2,200 wallet release charge to unlock your accumulated earnings."
    finding = await agent.investigate("TaskMatrix", None, "Bank Transfer", [], raw_text)

    # Must remain HIGH_RISK despite external provider failure
    assert finding.verdict == "HIGH_RISK"
    assert "UNLOCK_PAYMENT_DEMAND" in finding.details["risk_signals"]
    assert finding.details["provider_status"] == "FAILED"


@pytest.mark.asyncio
async def test_irrelevant_search_results_and_generic_advisories():
    """Generic scam advisories in search hits must not condemn an innocent company offer."""
    mock_search = MagicMock(spec=SerpApiClient)
    mock_search.search = AsyncMock(
        return_value={
            "source": SearchSource.REAL.value,
            "organic_results": [
                {
                    "title": "General Tips to Avoid Online Job Scams",
                    "link": "https://safety.example/guidelines",
                    "snippet": "General tips for job seekers on identifying fake offers.",
                }
            ],
        }
    )
    agent = ScamAgent(search_client=mock_search)

    raw_text = "Congratulations on your selection as Software Engineer at Acme Corp."
    finding = await agent.investigate("Acme Corp", None, None, [], raw_text)

    assert finding.verdict == "VERIFIED"
    assert finding.details["scam_flagged"] is False


@pytest.mark.asyncio
async def test_correct_final_reason_codes_and_needs_review_propagation():
    """Verify VerdictReasoner maps credential theft and unlock-payment reason codes accurately."""
    from app.services.risk.verdict_reasoner import VerdictReasoner
    from app.schemas.analysis import AgentFinding, RiskLevel

    reasoner = VerdictReasoner()

    # 1. Credential theft finding
    scam_cred = AgentFinding(
        agent_name="ScamAgent",
        verdict="HIGH_RISK",
        confidence=0.98,
        summary="Critical threat: Explicit solicitation of bank OTP and account passwords.",
        evidence=[],
        details={
            "risk_signals": ["CREDENTIAL_THEFT_DEMAND"],
            "reason_code": "CREDENTIAL_THEFT_DETECTED",
            "otp_requested": True,
        },
    )
    comp = AgentFinding(agent_name="CompanyAgent", verdict="CANNOT_VERIFY", confidence=0.0, summary="No records", evidence=[])
    rec = AgentFinding(agent_name="RecruiterAgent", verdict="CANNOT_VERIFY", confidence=0.0, summary="No records", evidence=[])
    sal = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.8, summary="Normal", evidence=[])

    res_cred = reasoner.evaluate(comp, rec, sal, scam_cred, 0.50, RiskLevel.HIGH_RISK)
    assert res_cred.verdict == RiskLevel.HIGH_RISK
    codes = [d.code for d in res_cred.reason_details]
    assert "CREDENTIAL_THEFT_DETECTED" in codes
    assert "ADVANCE_FEE_DETECTED" not in codes

    # 2. Unlock payment finding
    scam_unlock = AgentFinding(
        agent_name="ScamAgent",
        verdict="HIGH_RISK",
        confidence=0.98,
        summary="Advance payment required to release earned funds.",
        evidence=[],
        details={
            "risk_signals": ["UNLOCK_PAYMENT_DEMAND"],
            "reason_code": "UNLOCK_PAYMENT_DETECTED",
            "unlock_earnings_detected": True,
        },
    )
    res_unlock = reasoner.evaluate(comp, rec, sal, scam_unlock, 0.50, RiskLevel.HIGH_RISK)
    assert res_unlock.verdict == RiskLevel.HIGH_RISK
    codes_unlock = [d.code for d in res_unlock.reason_details]
    assert "UNLOCK_PAYMENT_DETECTED" in codes_unlock

    # 3. ScamAgent NEEDS_REVIEW propagates to VerdictReasoner
    scam_review = AgentFinding(
        agent_name="ScamAgent",
        verdict="NEEDS_REVIEW",
        confidence=0.70,
        summary="Telegram channel mentioned for announcements without payment requests; treated as caution.",
        evidence=[],
        details={"reason_code": "TELEGRAM_UNVERIFIED_CHANNEL"},
    )
    res_review = reasoner.evaluate(comp, rec, sal, scam_review, 0.20, RiskLevel.CANNOT_VERIFY)
    # When insufficient evidence makes overall verdict CANNOT_VERIFY, ScamAgent explanation must remain visible
    assert res_review.verdict == RiskLevel.CANNOT_VERIFY
    assert any("Telegram" in r for r in res_review.reasons)
    assert any(d.code == "TELEGRAM_UNVERIFIED_CHANNEL" for d in res_review.reason_details)


@pytest.mark.asyncio
async def test_secret_redaction_and_quote_span_consistency():
    """Verify secrets are redacted before storing quotes and source_span matches sanitized buffer."""
    from app.services.agents.scam_classifier import ScamClassifier, sanitize_and_redact_secrets

    raw_text = (
        "Your verification OTP is 738201. Please share your bank OTP 738201 and password SuperSecret#99 with HR."
    )
    sanitized = sanitize_and_redact_secrets(raw_text)

    # Secret values must NOT be present in sanitized buffer
    assert "738201" not in sanitized
    assert "SuperSecret#99" not in sanitized
    assert "[REDACTED_OTP]" in sanitized
    assert "[REDACTED_PASSWORD]" in sanitized

    classifier = ScamClassifier()
    assessments = classifier.classify(raw_text)

    cred_assessments = [a for a in assessments if a.signal_code == "CREDENTIAL_THEFT_DEMAND"]
    assert len(cred_assessments) >= 1
    quote = cred_assessments[0].source_quote
    span = cred_assessments[0].source_span

    # Quote must be sanitized
    assert "738201" not in quote
    assert "SuperSecret#99" not in quote

    # Span must match substring in sanitized buffer exactly
    if span:
        assert sanitized[span["start_offset"]:span["end_offset"]] == quote

