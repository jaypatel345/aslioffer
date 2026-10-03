import pytest
from app.schemas.analysis import AgentFinding
from app.services.agents.company_agent import CompanyAgent
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.agents.scam_agent import ScamAgent
from app.services.extractor.entity_extractor import EntityExtractor
from app.services.risk.risk_engine import RiskEngine
from .fixture_helpers import MockSearchClient, load_fixture_by_id


# ===========================================================================
# 1. Company Investigation Regressions
# ===========================================================================

@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: CompanyAgent._domain_matches treats brand name substring in lookalike domain as official, returning VERIFIED",
)
async def test_case_01_lookalike_domain_must_not_be_verified():
    """Case 1: A brand substring in a third-party domain (tcs-careers-portal.example) must not establish official ownership."""
    fixture = load_fixture_by_id("CASE-LOOKALIKE-DOMAIN-01")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = CompanyAgent(search_client=search_mock)
    finding = await agent.investigate(fixture["structured_input"]["company_name"])

    # Desired behavior: Substring match in lookalike domain must NOT verify the lookalike as official
    # Current buggy behavior: _domain_matches('https://tcs-careers-portal.example/apply', 'tcs') -> True -> VERIFIED
    assert finding.verdict != "VERIFIED"
    assert "tcs-careers-portal.example" not in (finding.details.get("official_domain") or "")


# ===========================================================================
# 2. Recruiter Investigation Regressions
# ===========================================================================

@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: RecruiterAgent falls through to VERIFIED and domain_match=True when official company domain is unresolved",
)
async def test_case_02_unknown_recruiter_unresolved_domain_must_not_pass():
    """Case 2: An unknown corporate-looking email cannot be certified as matching without an independently resolved company domain."""
    fixture = load_fixture_by_id("CASE-UNKNOWN-CORP-RECRUITER-02")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = RecruiterAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        recruiter_name=s_in["recruiter_name"],
        recruiter_email=s_in["recruiter_email"],
        recruiter_phone=s_in["recruiter_phone"],
    )

    # Desired behavior: Cannot verify recruiter without a confirmed official company domain
    # Current buggy behavior: Falls through to VERIFIED with details['domain_match'] = True
    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.details.get("domain_match") is not True


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: RecruiterAgent treats absence of public scam complaints for a phone number as VERIFIED",
)
async def test_case_03_phone_only_no_hits_must_not_verify():
    """Case 3: Clean search results on a phone number alone must remain inconclusive, not proof of legitimacy."""
    fixture = load_fixture_by_id("CASE-PHONE-ONLY-NO-MATCH-03")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = RecruiterAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        recruiter_name=s_in["recruiter_name"],
        recruiter_email=s_in["recruiter_email"],
        recruiter_phone=s_in["recruiter_phone"],
    )

    # Desired behavior: Absence of scam hits on a phone does not verify identity
    # Current buggy behavior: phone_flagged=False falls through to VERIFIED (confidence=0.88)
    assert finding.verdict == "CANNOT_VERIFY"


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: RecruiterAgent condemns legitimate recruitment agency domain as HIGH_RISK impersonation",
)
async def test_case_14_agency_recruitment_must_not_be_high_risk_impersonation():
    """Case 14: Third-party recruitment agencies use their own domain; requires verification, not immediate fraud conviction."""
    fixture = load_fixture_by_id("CASE-LEGIT-AGENCY-RECRUITMENT-14")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = RecruiterAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        recruiter_name=s_in["recruiter_name"],
        recruiter_email=s_in["recruiter_email"],
        recruiter_phone=s_in["recruiter_phone"],
    )

    # Desired behavior: Agency representation needs review/mandate check, not HIGH_RISK fraud flag
    # Current buggy behavior: domain mismatch between @apexstaffing and @wipro flags HIGH_RISK
    assert finding.verdict != "HIGH_RISK"
    assert finding.verdict == "NEEDS_REVIEW"


# ===========================================================================
# 3. Scam Detection Regressions
# ===========================================================================

@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: ScamAgent flags negated fee policies ('never charge a security deposit') as UPFRONT_FEE_DEMAND and HIGH_RISK",
)
async def test_case_04_negated_security_deposit_must_not_trigger_fee_demand():
    """Case 4: 'We never charge a security deposit' is an anti-fraud policy, not an upfront fee demand."""
    fixture = load_fixture_by_id("CASE-LEGIT-POLICY-NEGATED-FEE-04")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = ScamAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        demanded_fee=s_in["demanded_fee"],
        payment_method=s_in["payment_method"],
        flags=s_in["flags"],
        raw_text=fixture["raw_text"],
    )

    # Desired behavior: Negated fee recognized; no fee demand flagged
    # Current buggy behavior: 'security deposit' substring match triggers UPFRONT_FEE_DEMAND and HIGH_RISK
    assert finding.verdict == "VERIFIED"
    assert "UPFRONT_FEE_DEMAND" not in finding.details.get("risk_signals", [])


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: ScamAgent fails to distinguish quoted anti-scam warnings from active fee demands, returning HIGH_RISK",
)
async def test_case_05_quoted_scam_warning_must_not_trigger_fee_demand():
    """Case 5: Quoted anti-scam warnings warning candidates about fake fees must not be flagged as a fee demand."""
    fixture = load_fixture_by_id("CASE-QUOTED-SCAM-WARNING-05")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = ScamAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        demanded_fee=s_in["demanded_fee"],
        payment_method=s_in["payment_method"],
        flags=s_in["flags"],
        raw_text=fixture["raw_text"],
    )

    # Desired behavior: Quoted advisory does not trigger fee demand
    # Current buggy behavior: 'registration fee' substring triggers UPFRONT_FEE_DEMAND and HIGH_RISK
    assert finding.verdict == "VERIFIED"
    assert "UPFRONT_FEE_DEMAND" not in finding.details.get("risk_signals", [])


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: ScamAgent unconditionally flags any Telegram mention as critical HIGH_RISK fraud",
)
async def test_case_06_ordinary_telegram_mention_must_not_be_critical_fraud():
    """Case 6: An ordinary Telegram link for webinar announcements without fee demands must not be marked HIGH_RISK."""
    fixture = load_fixture_by_id("CASE-ORDINARY-TELEGRAM-06")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = ScamAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        demanded_fee=s_in["demanded_fee"],
        payment_method=s_in["payment_method"],
        flags=s_in["flags"],
        raw_text=fixture["raw_text"],
    )

    # Desired behavior: Telegram alone without payment or credential requests is not critical fraud
    # Current buggy behavior: 'telegram' substring in raw_lower unconditionally triggers HIGH_RISK
    assert finding.verdict != "HIGH_RISK"


@pytest.mark.asyncio
async def test_case_07_explicit_upfront_fee_triggers_high_risk():
    """Case 7: Explicit demand for advance security deposit via UPI correctly triggers HIGH_RISK (working behavior)."""
    fixture = load_fixture_by_id("CASE-EXPLICIT-UPFRONT-FEE-07")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = ScamAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        demanded_fee=s_in["demanded_fee"],
        payment_method=s_in["payment_method"],
        flags=s_in["flags"],
        raw_text=fixture["raw_text"],
    )

    # Working behavior: Upfront fee + UPI is correctly recognized as HIGH_RISK
    assert finding.verdict == "HIGH_RISK"
    assert "UPFRONT_FEE_DEMAND" in finding.details.get("risk_signals", [])
    assert finding.details.get("scam_flagged") is True


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: ScamAgent lacks explicit OTP and password credential theft detection, returning VERIFIED",
)
async def test_case_08_explicit_bank_otp_demand_must_trigger_high_risk():
    """Case 8: Soliciting a candidate's bank OTP or password must trigger immediate HIGH_RISK credential theft warning."""
    fixture = load_fixture_by_id("CASE-EXPLICIT-BANK-OTP-DEMAND-08")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = ScamAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        demanded_fee=s_in["demanded_fee"],
        payment_method=s_in["payment_method"],
        flags=s_in["flags"],
        raw_text=fixture["raw_text"],
    )

    # Desired behavior: Bank OTP / password demand must trigger HIGH_RISK
    # Current buggy behavior: ScamAgent does not check for OTP / password demands and returns VERIFIED
    assert finding.verdict == "HIGH_RISK"
    assert any("OTP" in s or "CREDENTIAL" in s for s in finding.details.get("risk_signals", []))


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: ScamAgent misses task-scam unlock-earnings payment demands not matching fixed keyword list",
)
async def test_case_09_payment_to_unlock_earnings_must_trigger_high_risk():
    """Case 9: Payment required to unlock earnings or task wages must trigger HIGH_RISK."""
    fixture = load_fixture_by_id("CASE-PAYMENT-TO-UNLOCK-JOB-09")
    search_mock = MockSearchClient(
        query_responses=fixture["search_mock"]["query_responses"],
        default_response=fixture["search_mock"]["default_response"],
    )
    agent = ScamAgent(search_client=search_mock)
    s_in = fixture["structured_input"]

    finding = await agent.investigate(
        company_name=s_in["company_name"],
        demanded_fee=s_in["demanded_fee"],
        payment_method=s_in["payment_method"],
        flags=s_in["flags"],
        raw_text=fixture["raw_text"],
    )

    # Desired behavior: Unlock-earnings demand detected as scam
    # Current buggy behavior: 'wallet release charge' does not match 8 fixed keywords and Bank Transfer is not UPI
    assert finding.verdict == "HIGH_RISK"


# ===========================================================================
# 4. Risk Synthesis and Evidence Conflation Regressions
# ===========================================================================

@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: RiskEngine conflates lack of evidence (CANNOT_VERIFY) with fraud, producing risk_score 0.60 and HIGH_RISK",
)
def test_case_10_sparse_employer_must_not_be_condemned_as_high_risk():
    """Case 10: Early-stage startup with sparse web footprint and no adverse signals must remain inconclusive, NOT HIGH_RISK."""
    engine = RiskEngine()

    fixture = load_fixture_by_id("CASE-SMALL-EMPLOYER-SPARSE-10")
    expected = fixture["expected_observations"]
    findings = [AgentFinding(agent_name=name, verdict=expected[key]["verdict"],
                             confidence=0.5, summary="Fixture assessment", evidence=[])
                for name, key in [("CompanyAgent", "company_assessment"),
                                  ("RecruiterAgent", "recruiter_assessment"),
                                  ("SalaryAgent", "salary_assessment"),
                                  ("ScamAgent", "scam_assessment")]]

    score, level, red_flags, green_flags = engine.compute_risk(findings)

    # Desired behavior: Inconclusive coverage is NOT fraud; must not be HIGH_RISK (score should not exceed 0.40)
    # Current buggy behavior: Adds 0.30 + 0.25 + 0.05 = 0.60 -> HIGH_RISK!
    assert level.value != "HIGH_RISK"
    assert score < 0.50


# ===========================================================================
# 5. Entity Extraction Regressions
# ===========================================================================

@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: EntityExtractor regex assigns candidate email as recruiter email when candidate email appears first",
)
def test_case_15_candidate_and_recruiter_email_role_separation():
    """Case 15: If candidate email appears before recruiter email, regex extractor must not assign candidate email to recruiter."""
    extractor = EntityExtractor()
    fixture = load_fixture_by_id("CASE-CANDIDATE-AND-RECRUITER-EMAILS-15")
    text = fixture["raw_text"]
    extracted = extractor.extract_regex(text)

    # Desired behavior: Recruiter email is talent.acquisition@tata-elxsi.example, NOT candidate.ananya@gmail.com
    # Current buggy behavior: First email matched is candidate.ananya@gmail.com, triggering PUBLIC_EMAIL_DOMAIN_USED flag
    assert extracted.recruiter_email == fixture["structured_input"]["recruiter_email"]
    assert "PUBLIC_EMAIL_DOMAIN_USED" not in extracted.flags


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Defect: EntityExtractor regex extracts 'Google' as company due to meeting URL/platform mention instead of actual employer V-Guard",
)
def test_case_16_company_extraction_trap_platform_mention():
    """Case 16: Meeting platform mentions (Google Meet) should not displace the actual employer name."""
    extractor = EntityExtractor()
    fixture = load_fixture_by_id("CASE-EXTRACTION-TRAP-PLATFORM-16")
    extracted = extractor.extract_regex(fixture["raw_text"])

    # Platform context handling in extractor:
    # Ensure Google Meet is not treated as company 'Google'
    assert extracted.company != "Google"
    assert extracted.company is not None and "V-Guard" in extracted.company



@pytest.mark.asyncio
async def test_case_11_empty_search_is_uncertainty():
    fixture = load_fixture_by_id("CASE-SUCCESSFUL-SEARCH-EMPTY-11")
    mock = MockSearchClient(**fixture["search_mock"])
    finding = await CompanyAgent(mock).investigate(fixture["structured_input"]["company_name"])
    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.details.get("official_domain") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_name", ["rate_limit", "authentication", "timeout"])
async def test_case_12_provider_failure_is_not_evidence(variant_name):
    fixture = load_fixture_by_id("CASE-PROVIDER-OUTAGE-TIMEOUT-12")
    variant = next(v for v in fixture["search_mock"]["variants"] if v["name"] == variant_name)
    query = next(iter(fixture["search_mock"]["query_responses"]))
    mock = MockSearchClient({query: variant["response"]}, variant["response"])
    finding = await CompanyAgent(mock).investigate(fixture["structured_input"]["company_name"])
    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.details.get("provider_status") == "FAILED"
    assert finding.details.get("error")
    assert finding.evidence == []


@pytest.mark.asyncio
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="Domain mismatch alone is treated as HIGH_RISK without checking possible agency affiliation")
async def test_case_13_plausible_details_do_not_confirm_offer_or_fraud():
    fixture = load_fixture_by_id("CASE-REALISTIC-IMPERSONATION-13")
    mock = MockSearchClient(**fixture["search_mock"])
    data = fixture["structured_input"]
    finding = await RecruiterAgent(mock).investigate(
        company_name=data["company_name"], recruiter_name=data["recruiter_name"],
        recruiter_email=data["recruiter_email"], recruiter_phone=data["recruiter_phone"])
    assert finding.verdict == fixture["expected_observations"]["recruiter_assessment"]["verdict"]
    assert finding.details.get("domain_match") is False
