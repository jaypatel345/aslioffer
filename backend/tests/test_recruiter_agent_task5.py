"""
Comprehensive regression test suite for Task 5: Recruiter Verification.
Validates:
- 6 explicit assessment dimensions and statuses.
- Safe contact validation (malformed email, normalization, exact phone boundary matching).
- Contextual adverse reports vs official listings and generic scam advice.
- Bounded recruiter affiliation searches and evidence strength hierarchy.
- Staffing agency footprint vs client representation mandate.
- RecruiterAgent authority and removal of ScamAgent duplicate free-email signal.
- Propagation through RiskEngine and VerdictReasoner (no false VERIFIED or HIGH_RISK).
- Partial search failures, demo isolation, search call budget, and private logging.
"""

import pytest
import logging
from unittest.mock import AsyncMock, MagicMock

from app.services.agents.recruiter_agent import RecruiterAgent, AssessmentStatus
from app.services.agents.scam_agent import ScamAgent
from app.services.risk.risk_engine import RiskEngine
from app.services.risk.verdict_reasoner import VerdictReasoner
from app.services.search.serpapi_client import SearchOutcome
from app.schemas.analysis import ExtractedEntities, RiskLevel


@pytest.fixture
def mock_serpapi():
    client = MagicMock()
    client.is_demo = False
    client.search = AsyncMock()
    return client


@pytest.fixture
def recruiter_agent(mock_serpapi):
    return RecruiterAgent(search_client=mock_serpapi)


def make_serp_response(items, outcome=SearchOutcome.SUCCESS, knowledge_graph=None, is_demo=False):
    is_success = outcome in (SearchOutcome.SUCCESS, SearchOutcome.ZERO_RESULTS)
    source = "DEMO" if is_demo else ("REAL" if is_success else "FAILED")
    return {
        "organic_results": items,
        "results": items,
        "outcome": outcome.value if isinstance(outcome, SearchOutcome) else outcome,
        "knowledge_graph": knowledge_graph or {},
        "source": source,
        "status": "successful" if is_success else "failed",
    }


# 1. Employer-domain match without person/offer affiliation evidence remains unconfirmed
@pytest.mark.asyncio
async def test_employer_domain_match_without_affiliation_remains_unconfirmed(recruiter_agent, mock_serpapi):
    """Domain match alone must NOT verify person or offer; affiliation remains UNCONFIRMED."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Official site of Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        return make_serp_response([])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="recruiter@acme.com",
        recruiter_name="Jane Doe",
    )

    assert finding.details["domain_match"] is True
    assert finding.details["employer_domain_resolution"]["status"] == AssessmentStatus.SUPPORTED.value
    assert finding.details["recruiter_email_domain"]["status"] == AssessmentStatus.SUPPORTED.value
    assert finding.details["recruiter_affiliation"]["status"] == AssessmentStatus.UNCONFIRMED.value
    assert finding.verdict == "CANNOT_VERIFY"
    assert "DOMAIN_MATCH_AFFILIATION_UNCONFIRMED" in finding.details.get("reason_code", "")
    assert "does not authenticate" in finding.summary.lower() or "could not be confirmed" in finding.summary.lower()


# 2. Specific employer-published recruiter/contact evidence supports stated relationship
@pytest.mark.asyncio
async def test_specific_employer_published_evidence_verifies_relationship_only(recruiter_agent, mock_serpapi):
    """Employer-published evidence mentioning person/contact verifies affiliation, but offer remains unauthenticated."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Careers & Leadership", "link": "https://acme.com", "snippet": "Acme Corp official site."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        # Affiliation query
        return make_serp_response([
            {
                "title": "Our Talent Team | Acme Corp",
                "link": "https://acme.com/team/jane-doe",
                "snippet": "Jane Doe is Lead Technical Recruiter at Acme Corp. Contact: jane.doe@acme.com",
            }
        ])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="jane.doe@acme.com",
        recruiter_name="Jane Doe",
    )

    assert finding.verdict == "VERIFIED"
    assert finding.details["domain_match"] is True
    assert finding.details["recruiter_affiliation"]["status"] == AssessmentStatus.SUPPORTED.value
    assert finding.details["recruiter_affiliation"]["evidence_strength"] == "strong_employer_published"
    assert "does not authenticate" in finding.summary.lower() or "unauthenticated" in finding.details["recruiter_affiliation"]["explanation"].lower()


# 3. Same-name unrelated person does not verify affiliation
@pytest.mark.asyncio
async def test_same_name_unrelated_person_does_not_verify_affiliation(recruiter_agent, mock_serpapi):
    """Finding Jane Doe at OtherCo must not verify affiliation with Acme Corp."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Welcome to Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        return make_serp_response([
            {
                "title": "Jane Doe - Graphic Designer - Beta LLC | LinkedIn",
                "link": "https://linkedin.com/in/janedoe-beta",
                "snippet": "Jane Doe is a graphic designer at Beta LLC in Chicago.",
            }
        ])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="jane.doe@acme.com",
        recruiter_name="Jane Doe",
    )

    assert finding.details["recruiter_affiliation"]["status"] == AssessmentStatus.UNCONFIRMED.value
    assert finding.verdict == "CANNOT_VERIFY"


# 4. Free email alone is not HIGH_RISK
@pytest.mark.asyncio
async def test_free_email_alone_is_needs_review(recruiter_agent, mock_serpapi):
    """Free webmail alone must yield NEEDS_REVIEW, never HIGH_RISK."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        return make_serp_response([])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="acme_recruiting@gmail.com",
        recruiter_name="John Recruiter",
    )

    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.details.get("reason_code") == "FREE_WEBMAIL_DOMAIN"
    assert finding.details["domain_match"] is False
    assert finding.details["recruiter_email_domain"]["is_free_webmail"] is True
    assert finding.details["recruiter_email_domain"]["status"] == AssessmentStatus.CONFLICTING.value


# 5. Different domain alone is NEEDS_REVIEW
@pytest.mark.asyncio
async def test_different_domain_alone_is_needs_review(recruiter_agent, mock_serpapi):
    """Domain mismatch without adverse reports must return NEEDS_REVIEW."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        return make_serp_response([])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="hiring@techhiringhub.com",
        recruiter_name="Alex Smith",
    )

    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.details.get("reason_code") == "RECRUITER_DOMAIN_MISMATCH"
    assert finding.details["domain_match"] is False
    assert finding.details["recruiter_email_domain"]["status"] == AssessmentStatus.CONFLICTING.value


# 6. Supported staffing agency with unconfirmed client mandate
@pytest.mark.asyncio
async def test_staffing_agency_identity_supported_but_mandate_unconfirmed(recruiter_agent, mock_serpapi):
    """Agency domain is verified, but authorization to hire for Acme is unconfirmed -> NEEDS_REVIEW."""
    async def mock_search(query):
        if "Acme Corp" in query and "careers" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        if "Apex Staffing" in query and "official website" in query:
            return make_serp_response(
                [{"title": "Apex Staffing Solutions Official Site", "link": "https://apexstaffing.com", "snippet": "Leading recruitment agency."}],
                knowledge_graph={"title": "Apex Staffing", "website": "https://apexstaffing.com"},
            )
        return make_serp_response([])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="recruiter@apexstaffing.com",
        recruiter_name="Sam Taylor",
        agency_name="Apex Staffing",
    )

    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.details.get("reason_code") == "AGENCY_MANDATE_UNCONFIRMED"
    assert finding.details["domain_match"] is False
    assert finding.details["agency_identity"]["status"] == AssessmentStatus.SUPPORTED.value
    assert finding.details["agency_authorization"]["status"] == AssessmentStatus.UNCONFIRMED.value


# 7. Agency self-claim versus employer-supported authorization
@pytest.mark.asyncio
async def test_agency_self_claim_vs_employer_supported_authorization(recruiter_agent, mock_serpapi):
    """Employer-published agency partnership is SUPPORTED."""
    async def mock_search(query):
        if "Acme Corp" in query and "careers" in query:
            return make_serp_response(
                [
                    {"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp official site. Preferred staffing partner: Apex Staffing."},
                    {"title": "Acme Partners", "link": "https://acme.com/partners", "snippet": "We work exclusively with Apex Staffing for engineering recruitment."}
                ],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        if "Apex Staffing" in query and "official website" in query:
            return make_serp_response(
                [{"title": "Apex Staffing Solutions Official Site", "link": "https://apexstaffing.com", "snippet": "Apex Staffing agency."}],
                knowledge_graph={"title": "Apex Staffing", "website": "https://apexstaffing.com"},
            )
        return make_serp_response([])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="recruiter@apexstaffing.com",
        recruiter_name="Sam Taylor",
        agency_name="Apex Staffing",
    )

    assert finding.details["agency_authorization"]["status"] == AssessmentStatus.SUPPORTED.value
    assert finding.details["agency_authorization"]["evidence_strength"] == "employer_published_partner"


# 8. Missing/invalid contacts and unresolved employer domains
@pytest.mark.asyncio
async def test_malformed_email_rejected_as_unusable_input(recruiter_agent, mock_serpapi):
    """Malformed email should be rejected as invalid input, not proof of fraud."""
    mock_serpapi.search.return_value = make_serp_response([])

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="not-an-email-address@@@@",
        recruiter_name="Jane Doe",
    )

    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.details.get("reason_code") == "INVALID_CONTACT_INPUT"
    assert finding.details["recruiter_email_domain"]["status"] == AssessmentStatus.NO_MATCH.value
    assert "malformed" in finding.details["recruiter_email_domain"]["explanation"].lower()


# 9. Official phone listing is not an adverse report
@pytest.mark.asyncio
async def test_official_phone_listing_is_not_an_adverse_report(recruiter_agent, mock_serpapi):
    """Phone number listed on official directory or helpdesk must NOT trigger adverse flag."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Official site."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        if "scam" in query:
            return make_serp_response([
                {
                    "title": "Contact Us | Acme Corp Headquarters",
                    "link": "https://acme.com/contact",
                    "snippet": "Reach Acme Corp corporate headquarters at +1 800-555-0199 for all inquiries.",
                }
            ])
        return make_serp_response([])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="jane@acme.com",
        recruiter_phone="+1-800-555-0199",
    )

    assert finding.details["adverse_contact_reports"]["status"] == AssessmentStatus.NO_MATCH.value
    assert finding.details["adverse_contact_reports"]["has_adverse_reports"] is False
    assert finding.verdict != "HIGH_RISK"


# 10. Generic warnings and incidental number mentions are not adverse reports
@pytest.mark.asyncio
async def test_generic_warning_mentioning_number_is_not_adverse(recruiter_agent, mock_serpapi):
    """A generic fraud advisory advising candidates to call an official support number is not adverse to that number."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        if "scam" in query:
            return make_serp_response([
                {
                    "title": "Security & Fraud Alert - Acme Careers",
                    "link": "https://acme.com/security",
                    "snippet": "Beware of fake job offers. If suspicious, verify immediately with Acme HR customer care helpline at +1-800-555-0199.",
                }
            ])
        return make_serp_response([])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="jane@acme.com",
        recruiter_phone="+1-800-555-0199",
    )

    assert finding.details["adverse_contact_reports"]["status"] == AssessmentStatus.NO_MATCH.value
    assert finding.details["adverse_contact_reports"]["has_adverse_reports"] is False


# 11. Specific exact-contact adverse reports remain visible
@pytest.mark.asyncio
async def test_specific_exact_contact_adverse_report_returns_high_risk(recruiter_agent, mock_serpapi):
    """An exact phone match on a consumer fraud complaint board returns HIGH_RISK."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        if "scam" in query:
            return make_serp_response([
                {
                    "title": "Reported Phone Scam - 415-555-2671",
                    "link": "https://scam-detector-community.example/report/4155552671",
                    "snippet": "Caller claimed from 415-555-2671 to be hiring for Acme Corp, asking for bank transfer fee.",
                }
            ])
        return make_serp_response([])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="jane@acme.com",
        recruiter_phone="+1 415-555-2671",
    )

    assert finding.verdict == "HIGH_RISK"
    assert finding.details.get("reason_code") == "ADVERSE_PHONE_REPORT"
    assert finding.details["adverse_contact_reports"]["status"] == AssessmentStatus.SUPPORTED.value
    assert finding.details["adverse_contact_reports"]["has_adverse_reports"] is True
    assert len(finding.details["adverse_contact_reports"]["reports"]) >= 1


# 12. Phone-format normalization and deceptive partial matches
@pytest.mark.asyncio
async def test_phone_format_rejects_unsafe_substring_matching(recruiter_agent, mock_serpapi):
    """555-1234 must not match 555-12345 or +1-800-555-1234 across title and snippet."""
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        return make_serp_response([
            {
                "title": "Scam Alert: 555-12345 is targeting job seekers",
                "link": "https://consumer-alerts.example/report/123",
                "snippet": "Do not answer calls from 555-12345, scammers are demanding money.",
            }
        ])

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_phone="555-1234",
    )

    assert finding.details["adverse_contact_reports"]["has_adverse_reports"] is False
    assert finding.details["adverse_contact_reports"]["status"] == AssessmentStatus.NO_MATCH.value


# 13. Successful empty searches versus each provider failure
@pytest.mark.asyncio
async def test_successful_empty_search_vs_provider_failure(recruiter_agent, mock_serpapi):
    """Empty search is NO_MATCH, while search failure is CHECK_UNAVAILABLE."""
    # Successful empty
    mock_serpapi.search.return_value = make_serp_response([], outcome=SearchOutcome.SUCCESS)

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_phone="+1 415 555 9999",
    )
    assert finding.details["adverse_contact_reports"]["status"] == AssessmentStatus.NO_MATCH.value

    # Provider failure
    mock_serpapi.search.return_value = make_serp_response([], outcome=SearchOutcome.PROVIDER_FAILURE)

    finding_fail = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_phone="+1 415 555 9999",
    )
    assert finding_fail.details["adverse_contact_reports"]["status"] == AssessmentStatus.CHECK_UNAVAILABLE.value


# 14. Partial failures retain successful affiliation/contact evidence
@pytest.mark.asyncio
async def test_partial_failures_retain_successful_evidence(recruiter_agent, mock_serpapi):
    """If phone search fails, affiliation and domain match results remain intact."""
    async def side_effect_search(query):
        if "phone" in query.lower() or "555" in query or "scam" in query:
            return make_serp_response([], outcome=SearchOutcome.PROVIDER_FAILURE)
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
            )
        return make_serp_response([
            {
                "title": "Jane Doe - Recruiter at Acme Corp",
                "link": "https://acme.com/team/jane",
                "snippet": "Jane Doe is the hiring manager at Acme Corp. Email: jane@acme.com",
            }
        ])

    mock_serpapi.search.side_effect = side_effect_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="jane@acme.com",
        recruiter_name="Jane Doe",
        recruiter_phone="+1-555-0199",
    )

    assert finding.details["domain_match"] is True
    assert finding.details["recruiter_affiliation"]["status"] == AssessmentStatus.SUPPORTED.value
    assert finding.details["adverse_contact_reports"]["status"] == AssessmentStatus.CHECK_UNAVAILABLE.value
    assert finding.details["provider_status"] == "PARTIAL"
    assert finding.verdict == "VERIFIED"


# 15. Demo/MOCK results cannot verify affiliation
@pytest.mark.asyncio
async def test_demo_mock_results_cannot_verify_affiliation(recruiter_agent, mock_serpapi):
    """When SerpApi is in demo mode, results must not produce VERIFIED affiliation."""
    mock_serpapi.is_demo = True
    async def mock_search(query):
        if "official website" in query:
            return make_serp_response(
                [{"title": "Acme Corp Official Site", "link": "https://acme.com", "snippet": "Acme Corp."}],
                knowledge_graph={"title": "Acme Corp", "website": "https://acme.com"},
                is_demo=True,
            )
        return make_serp_response(
            [
                {
                    "title": "Acme Corp Team - Jane Doe",
                    "link": "https://acme.com/team/jane",
                    "snippet": "Jane Doe recruiter at Acme Corp.",
                }
            ],
            is_demo=True,
        )

    mock_serpapi.search.side_effect = mock_search

    finding = await recruiter_agent.investigate(
        company_name="Acme Corp",
        recruiter_email="jane@acme.com",
        recruiter_name="Jane Doe",
    )

    assert finding.verdict != "VERIFIED"
    assert finding.details["recruiter_affiliation"]["status"] == AssessmentStatus.UNCONFIRMED.value


# 16. Search-call limits and private logging
@pytest.mark.asyncio
async def test_search_call_limits_and_private_logging(recruiter_agent, mock_serpapi, caplog):
    """Agent must execute at most 5 searches and not log raw recruiter phone/email in cleartext."""
    mock_serpapi.search.return_value = make_serp_response([])

    with caplog.at_level(logging.DEBUG):
        await recruiter_agent.investigate(
            company_name="Acme Corp",
            recruiter_email="secret_recruiter@acme.com",
            recruiter_name="Secret Agent",
            recruiter_phone="+1 415 888 7777",
            agency_name="Secret Agency",
        )

    assert mock_serpapi.search.call_count <= 5
    for record in caplog.records:
        assert "secret_recruiter@acme.com" not in record.message


# 17. Actual agents -> RiskEngine -> VerdictReasoner integration: free email produces NEEDS_REVIEW, not HIGH_RISK
@pytest.mark.asyncio
async def test_agents_to_risk_engine_to_verdict_reasoner_free_email_integration(mock_serpapi):
    """End-to-end integration: free email produces NEEDS_REVIEW from RecruiterAgent, no duplicate scam signal, final NEEDS_REVIEW."""
    mock_serpapi.search.return_value = make_serp_response([])
    recruiter_ag = RecruiterAgent(search_client=mock_serpapi)
    scam_ag = ScamAgent(search_client=mock_serpapi)

    entities = ExtractedEntities(
        company_name="Google",
        recruiter_name="John Recruiter",
        recruiter_email="google.recruiter@gmail.com",
        salary="$120,000",
    )

    recruiter_finding = await recruiter_ag.investigate(
        company_name=entities.company_name,
        recruiter_email=entities.recruiter_email,
        recruiter_name=entities.recruiter_name,
    )

    scam_finding = await scam_ag.investigate(
        company_name=entities.company_name,
        demanded_fee=None,
        payment_method=None,
        flags=[],
        raw_text="Congratulations on your offer with Google. We are pleased to offer you $120,000 per year.",
    )

    # 1. RecruiterAgent yields NEEDS_REVIEW for free email
    assert recruiter_finding.verdict == "NEEDS_REVIEW"
    assert recruiter_finding.details.get("reason_code") == "FREE_WEBMAIL_DOMAIN"

    # 2. ScamAgent does NOT produce PERSONAL_EMAIL_ENTERPRISE scam signal
    scam_signals = scam_finding.details.get("signals_detected", [])
    assert not any("email" in s.lower() or "personal" in s.lower() for s in scam_signals)
    assert scam_finding.verdict != "HIGH_RISK"

    # 3. RiskEngine evaluates findings
    risk_engine = RiskEngine()
    risk_score, risk_level, red_flags, green_flags = risk_engine.compute_risk([recruiter_finding, scam_finding])
    assert risk_level == RiskLevel.NEEDS_REVIEW

    # 4. VerdictReasoner evaluates final verdict
    reasoner = VerdictReasoner()
    from app.schemas.analysis import AgentFinding, EvidenceItem
    ev1 = EvidenceItem(source_url="https://google.com", title="Google Official Site", description="Corporate domain", evidence_type="COMPANY", confidence=0.9)
    ev2 = EvidenceItem(source_url="https://levels.fyi", title="Salary Benchmark", description="Salary benchmark within range", evidence_type="SALARY", confidence=0.9)
    dummy_company = AgentFinding(agent_name="CompanyAgent", verdict="VERIFIED", confidence=0.85, summary="Company found", evidence=[ev1])
    dummy_salary = AgentFinding(agent_name="SalaryAgent", verdict="VERIFIED", confidence=0.85, summary="Salary benchmark normal", evidence=[ev2])
    final_verdict = reasoner.evaluate(
        company_result=dummy_company,
        recruiter_result=recruiter_finding,
        salary_result=dummy_salary,
        scam_result=scam_finding,
        initial_risk_score=risk_score,
        initial_risk_level=risk_level,
    )
    assert final_verdict.verdict == RiskLevel.NEEDS_REVIEW
    assert final_verdict.verdict != RiskLevel.VERIFIED
    assert final_verdict.verdict != RiskLevel.HIGH_RISK
    assert any("recruiter" in r.lower() or "email" in r.lower() or "review" in r.lower() for r in final_verdict.reasons)
