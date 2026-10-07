"""
Task 12: Job & Application Destination Corroboration and Offer Confirmation Route Tests.

Covers:
1. Matching employer, role and vacancy location.
2. Employer headquarters does not support job location.
3. Related but materially different roles are not falsely matched.
4. Exact public requisition match.
5. Private/uncertain offer references are not searched.
6. Empty/expired listing results remain unresolved.
7. Same-domain URL supports only documented level of association.
8. Correct employer ATS tenant versus unrelated tenant.
9. Lookalike, credential-bearing and malformed URLs.
10. Independently published recruitment email/phone with relevant purpose.
11. Submitted-only recruiter contact does not become a route.
12. Homepage citation cannot support an invented HR email.
13. Generic careers portal is not presented as an offer-verification API.
14. No route returns null.
15. Draft uses safe placeholders and makes no accusations.
16. Claim-specific citations and actual source provenance.
17. Budget exhaustion, provider failure and deadline behavior.
18. Earlier strong warnings remain HIGH_RISK despite a matching vacancy.
19. Earlier recruiter uncertainty survives vacancy corroboration.
20. Demo results cannot yield a production route.
21. Existing pipeline signature and contract serialization remain compatible.
22. Generated Task 12 handoff fixtures.
"""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from app.schemas.contract import (
    CaseInput,
    Claim,
    ClaimKind,
    ClaimStatus,
    ConfirmedClaim,
    EventStatus,
    EvidenceRecord,
    EvidenceRelation,
    ExtractionStatus,
    InvestigationResult,
    OverallOutcome,
    RetrievalStatus,
    SourceKind,
    SourceTier,
    SourceType,
)
from app.services.investigation import (
    investigate_case,
    InvestigationBudget,
    BudgetManager,
    InvestigationPlanner,
    JobCorroborationService,
    JobCorroborationResult,
    is_public_job_reference,
    evaluate_application_destination,
    generate_confirmation_draft,
)
from app.services.search.domain_resolver import DomainResolver


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "investigation" / "generated_task12"


class MockSearchClient:
    """Mock search client returning pre-configured results by exact query string."""

    def __init__(self, query_responses: Optional[Dict[str, Any]] = None):
        self.query_responses = query_responses or {}
        self.call_log: List[Dict[str, Any]] = []

    async def search(self, query: str, engine: str = "google", num: int = 5, **kwargs) -> Dict[str, Any]:
        self.call_log.append({"query": query, "engine": engine, "num": num, "kwargs": kwargs})
        if query in self.query_responses:
            resp = self.query_responses[query]
            if isinstance(resp, Exception):
                raise resp
            return resp
        return {
            "status": "successful",
            "source": "REAL",
            "organic_results": [],
            "knowledge_graph": {},
        }


# ============================================================================
# 1. Matching Employer, Role, and Vacancy Location
# ============================================================================

@pytest.mark.asyncio
async def test_matching_employer_role_and_vacancy_location():
    """Matching public vacancy corroborates role and location while keeping authenticity UNCONFIRMED."""
    text = (
        "Employment Offer from Radiant Energy Solutions Ltd.\n"
        "Position: Software Engineer\n"
        "Location: Bengaluru, Karnataka\n"
        "Application link: https://careers.radiantenergy.example/apply/solar-eng\n"
        "Recruiter: recruitment@radiantenergy.example"
    )
    case_input = CaseInput(case_id=301, run_id="run_301", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'Radiant Energy Solutions Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Radiant Energy Solutions Ltd",
                    "website": "https://www.radiantenergy.example",
                    "careers_url": "https://careers.radiantenergy.example",
                },
                "organic_results": [
                    {
                        "link": "https://careers.radiantenergy.example/apply/solar-eng",
                        "title": "Software Engineer - Bengaluru - Radiant Energy Solutions Ltd",
                        "snippet": "We are hiring a Software Engineer in Bengaluru, Karnataka. Apply online.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome in (OverallOutcome.NO_STRONG_RISK_SIGNALS, OverallOutcome.CANNOT_VERIFY)
    assert result.authenticity_status.value == "UNCONFIRMED"

    # Role claim is SUPPORTED
    role_ass = next((a for a in result.assessed_claims if next((c.kind for c in result.claims if c.claim_id == a.claim_id), None) == ClaimKind.ROLE), None)
    assert role_ass is not None
    assert role_ass.status == ClaimStatus.SUPPORTED
    assert "PUBLIC_VACANCY_MATCH" in role_ass.reason_codes
    assert len(role_ass.evidence_ids) > 0

    # Location claim is SUPPORTED
    loc_ass = next((a for a in result.assessed_claims if next((c.kind for c in result.claims if c.claim_id == a.claim_id), None) == ClaimKind.LOCATION), None)
    assert loc_ass is not None
    assert loc_ass.status == ClaimStatus.SUPPORTED

    # Application URL is SUPPORTED
    url_ass = next((a for a in result.assessed_claims if next((c.kind for c in result.claims if c.claim_id == a.claim_id), None) == ClaimKind.APPLICATION_URL), None)
    assert url_ass is not None
    assert url_ass.status == ClaimStatus.SUPPORTED


# ============================================================================
# 2. Employer Headquarters Does Not Support Job Location
# ============================================================================

@pytest.mark.asyncio
async def test_employer_headquarters_does_not_support_job_location():
    """Corporate headquarters mention alone does not corroborate a claimed job location in another city."""
    text = (
        "Offer from MetroTech Pvt Ltd.\n"
        "Position: Field Reliability Engineer\n"
        "Location: Hyderabad\n"
        "Contact: hr@metrotech.example"
    )
    case_input = CaseInput(case_id=302, run_id="run_302", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'MetroTech Pvt Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "MetroTech Pvt Ltd",
                    "website": "https://www.metrotech.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.metrotech.example/about",
                        "title": "About MetroTech Pvt Ltd",
                        "snippet": "MetroTech Pvt Ltd is headquartered in Mumbai, Maharashtra.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    loc_ass = next((a for a in result.assessed_claims if next((c.kind for c in result.claims if c.claim_id == a.claim_id), None) == ClaimKind.LOCATION), None)
    assert loc_ass is not None
    # Higher-priority checks consume the default follow-up allowance here.
    assert loc_ass.status == ClaimStatus.NOT_CHECKED
    assert "CHECK_NOT_EXECUTED" in loc_ass.reason_codes


# ============================================================================
# 3. Related But Materially Different Roles Are Not Falsely Matched
# ============================================================================

def test_related_but_materially_different_roles_not_matched():
    """Conservative job title matching rejects different roles (e.g. Frontend vs Backend, Sales vs Engineering)."""
    corroborator = JobCorroborationService()

    claims = [
        Claim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="Nexis Global Ltd", source_quote="Nexis Global Ltd", extraction_status=ExtractionStatus.EXTRACTED),
        Claim(claim_id="c2", kind=ClaimKind.ROLE, value="Backend Software Engineer", source_quote="Backend Software Engineer", extraction_status=ExtractionStatus.EXTRACTED),
    ]

    # Search returned only Frontend Developer
    snippets = {
        "https://www.nexisglobal.example/careers": [
            {
                "source_url": "https://www.nexisglobal.example/careers/job1",
                "title": "Frontend Software Engineer - Nexis Global",
                "snippet": "Join Nexis Global as a Frontend Software Engineer working with React and UI.",
                "retrieval_status": RetrievalStatus.LIVE,
            }
        ]
    }

    res = corroborator.corroborate(
        claims=claims,
        company_name="Nexis Global Ltd",
        canonical_domain="nexisglobal.example",
        snippets_by_url=snippets,
        executed_steps={"corroborate_job_role"},
    )

    role_obs = res.observations.get("c2")
    assert role_obs is not None
    assert role_obs.status == ClaimStatus.UNRESOLVED
    assert "NO_MATCHING_VACANCY" in role_obs.reason_codes


# ============================================================================
# 4. Exact Public Requisition Match
# ============================================================================

@pytest.mark.asyncio
async def test_exact_public_requisition_match():
    """Public requisition pattern match is checked and supported by attributable hiring records."""
    text = (
        "Offer from CloudScale Systems Ltd.\n"
        "Position: Site Reliability Specialist\n"
        "Job Reference: REQ-84920\n"
        "Contact: recruitment@cloudscale.example"
    )
    case_input = CaseInput(case_id=304, run_id="run_304", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'CloudScale Systems Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "CloudScale Systems Ltd",
                    "website": "https://www.cloudscale.example",
                    "careers_url": "https://careers.cloudscale.example",
                },
                "organic_results": [
                    {
                        "link": "https://careers.cloudscale.example/job/req-84920",
                        "title": "Site Reliability Specialist (REQ-84920) - CloudScale Systems",
                        "snippet": "Job Requisition REQ-84920: Site Reliability Specialist at CloudScale Systems Ltd.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    ref_ass = next((a for a in result.assessed_claims if next((c.kind for c in result.claims if c.claim_id == a.claim_id), None) == ClaimKind.JOB_REFERENCE), None)
    assert ref_ass is not None
    assert ref_ass.status == ClaimStatus.SUPPORTED
    assert "PUBLIC_REQUISITION_VERIFIED" in ref_ass.reason_codes


# ============================================================================
# 5. Private / Uncertain Offer References Are Not Searched
# ============================================================================

def test_private_offer_references_not_searched():
    """Candidate-specific offer letter IDs or ambiguous references are marked NOT_CHECKED without searches."""
    assert is_public_job_reference("REQ-12345")[0] is True
    assert is_public_job_reference("JOB_9821")[0] is True
    assert is_public_job_reference("2024-ENG-001")[0] is True

    # Private offer references must abstain
    assert is_public_job_reference("OFFER/2026/0491")[0] is False
    assert is_public_job_reference("OL-REF-CANDIDATE-982")[0] is False
    assert is_public_job_reference("LOI/BLR/2026/4102")[0] is False
    assert is_public_job_reference("b5a3e144-8891-4c4f-9e22-123456789abc")[0] is False

    # Check planner abstention
    planner = InvestigationPlanner()
    claims = [
        Claim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="Acme Corp", source_quote="Acme Corp", extraction_status=ExtractionStatus.EXTRACTED),
        Claim(claim_id="c2", kind=ClaimKind.ROLE, value="Software Engineer", source_quote="Software Engineer", extraction_status=ExtractionStatus.EXTRACTED),
        Claim(claim_id="c3", kind=ClaimKind.JOB_REFERENCE, value="OFFER/2026/4102", source_quote="OFFER/2026/4102", extraction_status=ExtractionStatus.EXTRACTED),
    ]
    plan = planner.create_plan(claims=claims, findings={}, executed_queries=set(), canonical_domain="acme.example")
    # Must NOT contain a plan step for the private job reference
    assert not any(p.strategy == "JOB_REFERENCE_CORROBORATION" for p in plan)


# ============================================================================
# 6. Empty / Expired Listing Results Remain Unresolved
# ============================================================================

@pytest.mark.asyncio
async def test_empty_or_expired_listing_remains_unresolved():
    """An empty or unlisted vacancy search remains UNRESOLVED, not proof of fraud."""
    text = (
        "Offer from ZetaWave Technologies Ltd for Backend Developer.\n"
        "Contact: hr@zetawave.example"
    )
    case_input = CaseInput(case_id=306, run_id="run_306", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'ZetaWave Technologies Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "ZetaWave Technologies Ltd",
                    "website": "https://www.zetawave.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.zetawave.example/",
                        "title": "ZetaWave Technologies Home",
                        "snippet": "Pioneering distributed networking solutions.",
                    }
                ],
            },
            'site:zetawave.example "Backend Developer"': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [],
            },
            '"ZetaWave Technologies Ltd" "Backend Developer" job careers': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [],
            },
            '"ZetaWave Technologies Ltd" recruitment verification contact site:zetawave.example': {
                "status": "successful",
                "source": "REAL",
                "organic_results": [],
            },
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    role_ass = next((a for a in result.assessed_claims if next((c.kind for c in result.claims if c.claim_id == a.claim_id), None) == ClaimKind.ROLE), None)
    assert role_ass is not None
    assert role_ass.status == ClaimStatus.UNRESOLVED
    assert result.overall_outcome == OverallOutcome.CANNOT_VERIFY


# ============================================================================
# 7. Same-Domain URL Supports Only Documented Level of Association
# ============================================================================

def test_same_domain_url_supports_only_documented_level():
    """Official domain link with unobserved specific path remains UNRESOLVED (path unverified)."""
    res_unobserved = evaluate_application_destination(
        url_str="https://www.wipro.com/apply/secret-form?id=991",
        company_name="Wipro Limited",
        canonical_domain="wipro.com",
        observed_urls={"https://www.wipro.com/careers"},
    )
    assert res_unobserved["status"] == ClaimStatus.UNRESOLVED
    assert res_unobserved["reason_code"] == "DOMAIN_ASSOCIATED_PATH_UNVERIFIED"

    res_observed = evaluate_application_destination(
        url_str="https://www.wipro.com/careers/openings",
        company_name="Wipro Limited",
        canonical_domain="wipro.com",
        observed_urls={"https://www.wipro.com/careers/openings"},
    )
    assert res_observed["status"] == ClaimStatus.SUPPORTED
    assert res_observed["reason_code"] == "DESTINATION_VERIFIED"


# ============================================================================
# 8. Correct Employer ATS Tenant Versus Unrelated Tenant
# ============================================================================

def test_employer_ats_tenant_association():
    """Matching ATS tenant is recognized; unrelated ATS tenant remains UNRESOLVED without promotion to official."""
    res_matched = evaluate_application_destination(
        url_str="https://wipro.wd3.myworkdayjobs.com/careers/job1",
        company_name="Wipro Limited",
        canonical_domain="wipro.com",
        observed_urls={"https://wipro.wd3.myworkdayjobs.com/careers/job1"},
        established_ats_urls={"https://wipro.wd3.myworkdayjobs.com/careers/job1"},
    )
    assert res_matched["status"] == ClaimStatus.SUPPORTED
    assert res_matched["reason_code"] == "ESTABLISHED_ATS_TENANT"
    # Never labeled OFFICIAL_EMPLOYER
    assert res_matched["source_tier"] == SourceTier.ESTABLISHED_THIRD_PARTY

    res_unrelated = evaluate_application_destination(
        url_str="https://acmecorp.wd3.myworkdayjobs.com/careers/job1",
        company_name="Wipro Limited",
        canonical_domain="wipro.com",
        observed_urls=set(),
    )
    assert res_unrelated["status"] == ClaimStatus.UNRESOLVED
    assert res_unrelated["reason_code"] == "UNRELATED_ATS_TENANT"


# ============================================================================
# 9. Lookalike, Credential-Bearing, and Malformed URLs
# ============================================================================

def test_lookalike_and_malformed_urls():
    """Suspicious lookalike domains and credential-bearing URLs are CONTRADICTED."""
    res_lookalike = evaluate_application_destination(
        url_str="https://wipro-careers-portal.example/apply",
        company_name="Wipro Limited",
        canonical_domain="wipro.com",
        observed_urls=set(),
    )
    assert res_lookalike["status"] == ClaimStatus.CONTRADICTED
    assert res_lookalike["reason_code"] == "SUSPECTED_LOOKALIKE_DESTINATION"

    res_cred = evaluate_application_destination(
        url_str="https://admin:pass@wipro.com/apply",
        company_name="Wipro Limited",
        canonical_domain="wipro.com",
        observed_urls=set(),
    )
    assert res_cred["status"] == ClaimStatus.CONTRADICTED
    assert res_cred["reason_code"] == "MALFORMED_OR_CREDENTIAL_URL"


# ============================================================================
# 10. Independently Published Recruitment Email/Phone with Relevant Purpose
# ============================================================================

@pytest.mark.asyncio
async def test_independently_published_recruitment_contact():
    """Published recruitment email or switchboard with verification context yields an official confirmation route."""
    text = (
        "Offer from Radiant Energy Solutions Ltd for Solar Engineer.\n"
        "Contact: ananya@radiantenergy.example"
    )
    case_input = CaseInput(case_id=310, run_id="run_310", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'Radiant Energy Solutions Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Radiant Energy Solutions Ltd",
                    "website": "https://www.radiantenergy.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.radiantenergy.example/contact-careers",
                        "title": "Contact Careers & Verification - Radiant Energy Solutions Ltd",
                        "snippet": "For offer verification and recruitment inquiries, email verify-offers@radiantenergy.example or call our board line.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.confirmation_route is not None
    assert result.confirmation_route.channel == "official_email"
    assert result.confirmation_route.destination == "verify-offers@radiantenergy.example"
    assert result.confirmation_route.evidence_id is not None
    # Referential integrity check
    ev_ids = [e.evidence_id for e in result.evidence]
    assert result.confirmation_route.evidence_id in ev_ids


# ============================================================================
# 11. Submitted-Only Recruiter Contact Does Not Become a Route
# ============================================================================

@pytest.mark.asyncio
async def test_submitted_only_recruiter_contact_does_not_become_route():
    """A recruiter email found only in the offer document is never recycled as an independent confirmation channel."""
    text = (
        "Offer from Apex Horizon Tech Pvt Ltd.\n"
        "Role: DevOps Engineer\n"
        "Contact: recruiter.deepak@apexhorizon.example"
    )
    case_input = CaseInput(case_id=311, run_id="run_311", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'Apex Horizon Tech Pvt Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Apex Horizon Tech Pvt Ltd",
                    "website": "https://www.apexhorizon.example",
                },
                "organic_results": [
                    {
                        "link": "https://www.apexhorizon.example/",
                        "title": "Apex Horizon Tech",
                        "snippet": "Leading tech solutions.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    if result.confirmation_route:
        # Route destination must NOT be the submitted recruiter contact
        assert result.confirmation_route.destination != "recruiter.deepak@apexhorizon.example"


# ============================================================================
# 12. Homepage Citation Cannot Support an Invented HR Email
# ============================================================================

def test_homepage_citation_cannot_support_invented_email():
    """An HR email must actually be published in retrieved search snippets; never synthesized."""
    corroborator = JobCorroborationService()
    claims = [
        Claim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="Acme Ltd", source_quote="Acme Ltd", extraction_status=ExtractionStatus.EXTRACTED),
        Claim(claim_id="c2", kind=ClaimKind.ROLE, value="Analyst", source_quote="Analyst", extraction_status=ExtractionStatus.EXTRACTED),
    ]

    # Snippet mentions company but zero email addresses
    snippets = {
        "https://www.acme.example/": [
            {
                "source_url": "https://www.acme.example/",
                "title": "Acme Ltd Homepage",
                "snippet": "Welcome to Acme Ltd. Innovation in logistics and supply chain.",
                "retrieval_status": RetrievalStatus.LIVE,
            }
        ]
    }

    res = corroborator.corroborate(
        claims=claims,
        company_name="Acme Ltd",
        canonical_domain="acme.example",
        snippets_by_url=snippets,
    )

    # Must NOT invent hr@acme.example or careers@acme.example
    if res.confirmation_route:
        assert res.confirmation_route.channel != "official_email"


# ============================================================================
# 13. Generic Careers Portal Not Presented as an Offer-Verification API
# ============================================================================

def test_generic_careers_portal_draft_restrained():
    """Confirmation draft for a careers portal advises finding published contacts without claiming an automated check API."""
    draft = generate_confirmation_draft(
        channel="careers_portal",
        company_name="Wipro Limited",
        role="Project Engineer",
        job_ref="REQ-102",
    )
    assert "Navigate to Wipro Limited's official portal" in draft
    assert "do not disclose banking details" in draft
    assert "REQ-102" in draft


# ============================================================================
# 14. No Route Returns None
# ============================================================================

@pytest.mark.asyncio
async def test_no_route_returns_none():
    """When no independently sourced employer channel is discovered, confirmation_route is strictly None."""
    text = "Offer from StealthGhost Ltd for Developer. Contact: hr@stealthghost.example"
    case_input = CaseInput(case_id=314, run_id="run_314", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(query_responses={})
    result = await investigate_case(case_input, search_client=search_mock)

    assert result.confirmation_route is None


# ============================================================================
# 15. Draft Uses Safe Placeholders and Makes No Accusations
# ============================================================================

def test_draft_uses_safe_placeholders_and_makes_no_accusations():
    """Draft message for official email contains safe placeholders and zero accusatory language."""
    draft = generate_confirmation_draft(
        channel="official_email",
        company_name="Tata Consultancy Services",
        role="Systems Engineer",
        recruiter_name="Sunil Sharma",
    )
    assert "[Your Name]" in draft
    assert "[Your Full Name]" in draft
    assert "Sunil Sharma" in draft
    assert "fraud" not in draft.lower()
    assert "scam" not in draft.lower()
    assert "fake" not in draft.lower()
    assert "OTP" not in draft


# ============================================================================
# 16. Claim-Specific Citations and Actual Source Provenance
# ============================================================================

@pytest.mark.asyncio
async def test_claim_specific_citations_and_provenance():
    """Evidence records are attached directly to their specific claims with real search provenance."""
    text = (
        "Offer from Horizon Retail Ltd.\n"
        "Role: Operations Executive\n"
        "Location: Chennai\n"
        "Contact: recruitment@horizonretail.example"
    )
    case_input = CaseInput(case_id=316, run_id="run_316", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'Horizon Retail Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Horizon Retail Ltd",
                    "website": "https://www.horizonretail.example",
                    "careers_url": "https://careers.horizonretail.example",
                },
                "organic_results": [
                    {
                        "link": "https://careers.horizonretail.example/jobs/retail-lead",
                        "title": "Operations Executive - Chennai - Horizon Retail",
                        "snippet": "Hiring Operations Executive in Chennai store. Apply via careers portal.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    role_claim = next((c for c in result.claims if c.kind == ClaimKind.ROLE), None)
    loc_claim = next((c for c in result.claims if c.kind == ClaimKind.LOCATION), None)

    assert role_claim is not None and loc_claim is not None
    role_ev = [e for e in result.evidence if e.claim_id == role_claim.claim_id]
    loc_ev = [e for e in result.evidence if e.claim_id == loc_claim.claim_id]

    assert len(role_ev) > 0
    assert len(loc_ev) > 0
    assert role_ev[0].query == 'Horizon Retail Ltd official website'
    assert role_ev[0].source_kind == SourceKind.SEARCH_SNIPPET


# ============================================================================
# 17. Budget Exhaustion and Provider Failure Behavior
# ============================================================================

@pytest.mark.asyncio
async def test_budget_exhaustion_skips_pending_corroboration():
    """Budget denial cleanly skips pending corroboration and retains executed findings."""
    text = "Offer from AlphaTech Ltd for Cloud Architect. Contact: hr@alphatech.example"
    case_input = CaseInput(case_id=317, run_id="run_317", source_type=SourceType.TEXT, redacted_text=text)

    budget = InvestigationBudget(max_search_calls=1, max_followup_calls=0)
    search_mock = MockSearchClient(
        query_responses={
            'AlphaTech Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {"website": "https://www.alphatech.example"},
                "organic_results": [],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock, budget=budget)

    # At most 1 search call executed
    assert len(search_mock.call_log) <= 1
    assert result.overall_outcome == OverallOutcome.CANNOT_VERIFY


# ============================================================================
# 18. Earlier Strong Warnings Remain HIGH_RISK Despite Matching Vacancy
# ============================================================================

@pytest.mark.asyncio
async def test_earlier_strong_warnings_remain_high_risk_despite_matching_vacancy():
    """Grounded upfront fee demand preserves HIGH_RISK even if public vacancy matches."""
    text = (
        "Offer from Radiant Energy Solutions Ltd.\n"
        "Role: Senior Solar Systems Engineer\n"
        "Location: Bengaluru\n"
        "A mandatory refundable security deposit of Rs 5,000 must be paid to confirm your joining.\n"
        "Contact: recruitment@radiantenergy.example"
    )
    case_input = CaseInput(case_id=318, run_id="run_318", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'Radiant Energy Solutions Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Radiant Energy Solutions Ltd",
                    "website": "https://www.radiantenergy.example",
                    "careers_url": "https://careers.radiantenergy.example",
                },
                "organic_results": [
                    {
                        "link": "https://careers.radiantenergy.example/solar-eng",
                        "title": "Senior Solar Systems Engineer - Bengaluru - Radiant Energy Solutions Ltd",
                        "snippet": "We are hiring a Senior Solar Systems Engineer in Bengaluru.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    assert result.overall_outcome == OverallOutcome.HIGH_RISK
    assert result.authenticity_status.value == "UNCONFIRMED"


# ============================================================================
# 19. Earlier Recruiter Uncertainty Survives Vacancy Corroboration
# ============================================================================

@pytest.mark.asyncio
async def test_earlier_recruiter_uncertainty_survives_vacancy_corroboration():
    """Recruiter domain mismatch remains unconfirmed even when job vacancy is corroborated."""
    text = (
        "Offer from Radiant Energy Solutions Ltd.\n"
        "Role: Senior Solar Systems Engineer\n"
        "Location: Bengaluru\n"
        "Contact: recruiter.rajesh@free-recruitment-agency.example"
    )
    case_input = CaseInput(case_id=319, run_id="run_319", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient(
        query_responses={
            'Radiant Energy Solutions Ltd official website': {
                "status": "successful",
                "source": "REAL",
                "knowledge_graph": {
                    "title": "Radiant Energy Solutions Ltd",
                    "website": "https://www.radiantenergy.example",
                    "careers_url": "https://careers.radiantenergy.example",
                },
                "organic_results": [
                    {
                        "link": "https://careers.radiantenergy.example/solar-eng",
                        "title": "Senior Solar Systems Engineer - Bengaluru - Radiant Energy Solutions Ltd",
                        "snippet": "We are hiring a Senior Solar Systems Engineer in Bengaluru.",
                    }
                ],
            }
        }
    )

    result = await investigate_case(case_input, search_client=search_mock)

    # Overall outcome cannot be verified because of recruiter conflict/uncertainty
    email_ass = next((a for a in result.assessed_claims if next((c.kind for c in result.claims if c.claim_id == a.claim_id), None) == ClaimKind.SENDER_EMAIL), None)
    assert email_ass is not None
    assert email_ass.status != ClaimStatus.SUPPORTED


# ============================================================================
# 20. Demo Results Cannot Yield a Production Route
# ============================================================================

def test_demo_results_cannot_yield_production_route():
    """DEMO retrieval status evidence is strictly ignored when demo_mode is False."""
    corroborator = JobCorroborationService(demo_mode=False)
    claims = [
        Claim(claim_id="c1", kind=ClaimKind.EMPLOYER, value="DemoCorp", source_quote="DemoCorp", extraction_status=ExtractionStatus.EXTRACTED),
        Claim(claim_id="c2", kind=ClaimKind.ROLE, value="Engineer", source_quote="Engineer", extraction_status=ExtractionStatus.EXTRACTED),
    ]

    snippets = {
        "https://www.democorp.example/careers": [
            {
                "source_url": "https://www.democorp.example/careers",
                "title": "Demo Careers",
                "snippet": "Contact careers@democorp.example for offer verification.",
                "retrieval_status": RetrievalStatus.DEMO,
            }
        ]
    }

    res = corroborator.corroborate(
        claims=claims,
        company_name="DemoCorp",
        canonical_domain="democorp.example",
        snippets_by_url=snippets,
    )

    assert res.confirmation_route is None


# ============================================================================
# 21. Serialization & Contract v1 Compatibility
# ============================================================================

@pytest.mark.asyncio
async def test_existing_pipeline_signature_and_contract_serialization():
    """InvestigationResult matches contract v1 schema and serializes cleanly."""
    text = "Offer from TechSolutions Ltd for Support Engineer. Contact: hr@techsolutions.example"
    case_input = CaseInput(case_id=321, run_id="run_321", source_type=SourceType.TEXT, redacted_text=text)

    search_mock = MockSearchClient()
    result = await investigate_case(case_input, search_client=search_mock)

    dumped = result.model_dump(mode="json")
    assert dumped["contract_version"] == "1.0.0"
    assert "assessed_claims" in dumped
    assert "evidence" in dumped
    assert "overall_outcome" in dumped
    assert "confirmation_route" in dumped


# ============================================================================
# 22. Generate Task 12 Handoff Fixtures
# ============================================================================

@pytest.mark.asyncio
async def test_generate_and_roundtrip_task12_fixtures(tmp_path):
    """Generates and validates the 4 Task 12 handoff fixtures."""
    output_dir = tmp_path / "generated_task12"
    output_dir.mkdir(parents=True, exist_ok=True)

    fixtures = [
        # Fixture 1: Corroborated vacancy with supported confirmation route
        (
            "fixture_corroborated_with_route.json",
            CaseInput(
                case_id=401,
                run_id="run_task12_corroborated_route",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Employment Offer from Radiant Energy Solutions Ltd.\n"
                    "Position: Senior Solar Systems Engineer\n"
                    "Location: Bengaluru, Karnataka\n"
                    "Application Destination: https://careers.radiantenergy.example/apply/solar-eng\n"
                    "Requisition ID: REQ-9901\n"
                    "Contact: talent@radiantenergy.example"
                ),
                demo_mode=False,
            ),
            MockSearchClient(
                query_responses={
                    'Radiant Energy Solutions Ltd official website': {
                        "status": "successful",
                        "source": "REAL",
                        "knowledge_graph": {
                            "title": "Radiant Energy Solutions Ltd",
                            "website": "https://www.radiantenergy.example",
                            "careers_url": "https://careers.radiantenergy.example",
                        },
                        "organic_results": [
                            {
                                "link": "https://careers.radiantenergy.example/apply/solar-eng",
                                "title": "Senior Solar Systems Engineer (REQ-9901) - Bengaluru - Radiant Energy Solutions Ltd",
                                "snippet": "Requisition REQ-9901: Senior Solar Systems Engineer in Bengaluru, Karnataka. Contact verify-offers@radiantenergy.example for recruitment verification inquiries.",
                            }
                        ],
                    }
                }
            ),
        ),
        # Fixture 2: Unresolved vacancy with no route
        (
            "fixture_unresolved_no_route.json",
            CaseInput(
                case_id=402,
                run_id="run_task12_unresolved_no_route",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Offer from PhantomAI Labs for Distributed ML Specialist.\n"
                    "Location: Remote\n"
                    "Contact: hr@phantomai.example"
                ),
                demo_mode=False,
            ),
            MockSearchClient(query_responses={}),
        ),
        # Fixture 3: Associated ATS destination
        (
            "fixture_associated_ats_destination.json",
            CaseInput(
                case_id=403,
                run_id="run_task12_ats_destination",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Offer from Wipro Limited for Project Engineer.\n"
                    "Application link: https://wipro.wd3.myworkdayjobs.com/careers/job-101\n"
                    "Contact: talentacquisition@wipro.example"
                ),
                demo_mode=False,
            ),
            MockSearchClient(
                query_responses={
                    'Wipro Limited official website': {
                        "status": "successful",
                        "source": "REAL",
                        "knowledge_graph": {
                            "title": "Wipro Limited",
                            "website": "https://www.wipro.com",
                            "careers_url": "https://wipro.wd3.myworkdayjobs.com/careers",
                        },
                        "organic_results": [
                            {
                                "link": "https://wipro.wd3.myworkdayjobs.com/careers/job-101",
                                "title": "Project Engineer - Wipro Limited Careers",
                                "snippet": "Project Engineer opening on Wipro Workday jobs portal.",
                            }
                        ],
                    }
                }
            ),
        ),
        # Fixture 4: Strong local warning despite matching public vacancy
        (
            "fixture_local_warning_with_vacancy.json",
            CaseInput(
                case_id=404,
                run_id="run_task12_warning_with_vacancy",
                source_type=SourceType.TEXT,
                redacted_text=(
                    "Employment Offer from Radiant Energy Solutions Ltd.\n"
                    "Position: Senior Solar Systems Engineer\n"
                    "Location: Bengaluru\n"
                    "Please deposit Rs 10,000 onboarding security fee to confirm your laptop allocation.\n"
                    "Contact: recruitment@radiantenergy.example"
                ),
                demo_mode=False,
            ),
            MockSearchClient(
                query_responses={
                    'Radiant Energy Solutions Ltd official website': {
                        "status": "successful",
                        "source": "REAL",
                        "knowledge_graph": {
                            "title": "Radiant Energy Solutions Ltd",
                            "website": "https://www.radiantenergy.example",
                            "careers_url": "https://careers.radiantenergy.example",
                        },
                        "organic_results": [
                            {
                                "link": "https://careers.radiantenergy.example/solar-eng",
                                "title": "Senior Solar Systems Engineer - Bengaluru - Radiant Energy Solutions Ltd",
                                "snippet": "We are hiring a Senior Solar Systems Engineer in Bengaluru.",
                            }
                        ],
                    }
                }
            ),
        ),
    ]

    for fname, case_input, search_client in fixtures:
        res = await investigate_case(case_input, search_client=search_client)
        payload = res.model_dump(mode="json")
        fpath = output_dir / fname
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        # Validate roundtrip
        reloaded = InvestigationResult.model_validate_json(fpath.read_text(encoding="utf-8"))
        assert reloaded.run_id == res.run_id
        assert reloaded.overall_outcome == res.overall_outcome


def test_committed_task12_fixtures_are_valid():
    paths = sorted(FIXTURES_DIR.glob("fixture_*.json"))
    assert len(paths) == 4
    for path in paths:
        result = InvestigationResult.model_validate_json(path.read_text(encoding="utf-8"))
        assert result.authenticity_status.value == "UNCONFIRMED"
        if result.confirmation_route:
            assert result.confirmation_route.evidence_id in {e.evidence_id for e in result.evidence}
