"""
Unit and regression tests for DomainResolver and agent domain resolution (Task 4).
Tests run completely offline with no network calls or external downloads.
"""
import pytest
from app.schemas.analysis import AgentFinding
from app.services.agents.company_agent import CompanyAgent
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.search.serpapi_client import SearchOutcome, SearchResult
from app.services.search.domain_resolver import (
    DomainResolver,
    DomainResolutionState,
    ParsedDomain,
)


# Mock search client that returns preconfigured SearchResult objects
class MockSearch:
    def __init__(self, result: SearchResult):
        self._result = result

    async def search(self, query: str, **kwargs):
        return self._result


# =============================================================================
# 1. Well-supported company identity and canonical website
# =============================================================================

def test_well_supported_company_identity_and_canonical_website():
    """Well-supported company identity with aligned Knowledge Graph and organic hits resolves cleanly."""
    search_res = SearchResult(
        query='"Wipro Limited" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        knowledge_graph={
            "title": "Wipro Limited",
            "website": "https://www.wipro.com",
            "careers_url": "https://www.wipro.com/careers",
        },
        results=[
            {
                "title": "Wipro: IT Services & Consulting",
                "link": "https://www.wipro.com",
                "snippet": "Wipro is a leading technology services and consulting company.",
            },
            {
                "title": "Careers at Wipro",
                "link": "https://www.wipro.com/careers",
                "snippet": "Explore job opportunities and career paths at Wipro.",
            },
        ],
    )

    resolution = DomainResolver.resolve("Wipro Limited", search_res)
    assert resolution.state == DomainResolutionState.RESOLVED
    assert resolution.canonical_domain == "www.wipro.com"
    assert resolution.canonical_url == "https://www.wipro.com"
    assert resolution.careers_url == "https://www.wipro.com/careers"
    assert resolution.confidence >= 0.90
    assert len(resolution.evidence) >= 2


# =============================================================================
# 2. Lookalike brand-containing hostname
# =============================================================================

def test_lookalike_brand_containing_hostname():
    """Lookalike domain with brand and portal keyword concatenation must be rejected."""
    search_res = SearchResult(
        query='"Tata Consultancy Services" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        results=[
            {
                "title": "TCS Careers Portal - Latest Openings",
                "link": "https://tcs-careers-portal.example/apply",
                "snippet": "Submit your job applications for TCS vacancies.",
            }
        ],
    )

    resolution = DomainResolver.resolve("Tata Consultancy Services", search_res)
    assert resolution.state == DomainResolutionState.UNRESOLVED
    assert resolution.canonical_domain is None
    assert resolution.canonical_url is None
    assert any("lookalike" in r.get("reason", "").lower() for r in resolution.rejected_candidates)


# =============================================================================
# 3. Brand in an attacker-controlled subdomain
# =============================================================================

def test_brand_in_attacker_controlled_subdomain():
    """Brand name in a subdomain of an unrelated registrable domain must be rejected."""
    search_res = SearchResult(
        query='"Tata Consultancy Services" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        results=[
            {
                "title": "TCS Careers - Job Portal",
                "link": "https://tcs.com.attacker.example/job-openings",
                "snippet": "Apply for jobs at Tata Consultancy Services.",
            }
        ],
    )

    resolution = DomainResolver.resolve("Tata Consultancy Services", search_res)
    assert resolution.state == DomainResolutionState.UNRESOLVED
    assert resolution.canonical_domain is None
    assert any("subdomain" in r.get("reason", "").lower() for r in resolution.rejected_candidates)


# =============================================================================
# 4. Brand or domain appearing only in a URL path
# =============================================================================

def test_brand_appearing_only_in_url_path():
    """Brand/domain name appearing only in URL path of an unrelated host must be rejected."""
    search_res = SearchResult(
        query='"Tata Consultancy Services" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        results=[
            {
                "title": "Job Openings",
                "link": "https://attacker.example/tcs.com/apply",
                "snippet": "Apply to TCS jobs here.",
            }
        ],
    )

    resolution = DomainResolver.resolve("Tata Consultancy Services", search_res)
    assert resolution.state == DomainResolutionState.UNRESOLVED
    assert resolution.canonical_domain is None
    assert any("does not align" in r.get("reason", "").lower() for r in resolution.rejected_candidates)


# =============================================================================
# 5. Unrelated Knowledge Graph identity
# =============================================================================

def test_unrelated_knowledge_graph_identity():
    """Knowledge graph representing an unrelated entity must not be accepted."""
    search_res = SearchResult(
        query='"Apex Horizon Tech" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        knowledge_graph={
            "title": "Apex Tool Group",
            "website": "https://www.apextoolgroup.example",
        },
        results=[],
    )

    resolution = DomainResolver.resolve("Apex Horizon Tech", search_res)
    assert resolution.state == DomainResolutionState.UNRESOLVED
    assert resolution.canonical_domain is None
    assert any("does not match claimed company" in r.get("reason", "").lower() for r in resolution.rejected_candidates)


# =============================================================================
# 6. Insufficient Knowledge Graph identity
# =============================================================================

def test_insufficient_knowledge_graph_identity():
    """Knowledge graph website without an entity title lacks sufficient identity to resolve."""
    search_res = SearchResult(
        query='"Apex Horizon Tech" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        knowledge_graph={
            "website": "https://www.apexhorizon.example",
            # title is intentionally omitted
        },
        results=[],
    )

    resolution = DomainResolver.resolve("Apex Horizon Tech", search_res)
    assert resolution.state == DomainResolutionState.UNRESOLVED
    assert resolution.canonical_domain is None
    assert any("lacks entity title" in r.get("reason", "").lower() for r in resolution.rejected_candidates)


# =============================================================================
# 7. Similar company names and ambiguous candidates
# =============================================================================

def test_similar_company_names_and_ambiguous_candidates():
    """Multiple competing plausible corporate domains without decisive corroboration yield AMBIGUOUS."""
    search_res = SearchResult(
        query='"Apex Technologies" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        results=[
            {
                "title": "Apex - Enterprise Cloud Platform",
                "link": "https://www.apex.example",
                "snippet": "Apex is an enterprise cloud and technology platform.",
            },
            {
                "title": "Apex Technologies - IT Solutions",
                "link": "https://www.apextechnologies.example",
                "snippet": "Apex Technologies provides cloud consulting and IT services.",
            },
        ],
    )

    resolution = DomainResolver.resolve("Apex Technologies", search_res)
    assert resolution.state == DomainResolutionState.AMBIGUOUS
    assert resolution.canonical_domain is None
    assert "ambiguous" in resolution.basis.lower()


# =============================================================================
# 8. Social and directory results ranked first
# =============================================================================

def test_social_and_directory_results_ranked_first():
    """Rank-1 social media, directory, or encyclopedia links must not become official company website."""
    search_res = SearchResult(
        query='"Tata Consultancy Services" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        results=[
            {
                "title": "Tata Consultancy Services | LinkedIn",
                "link": "https://www.linkedin.com/company/tata-consultancy-services",
                "snippet": "Tata Consultancy Services is a global leader in IT services.",
            },
            {
                "title": "Tata Consultancy Services - Wikipedia",
                "link": "https://en.wikipedia.org/wiki/Tata_Consultancy_Services",
                "snippet": "TCS is an Indian multinational information technology services and consulting company.",
            },
            {
                "title": "TCS Jobs on Naukri.com",
                "link": "https://www.naukri.com/tcs-jobs",
                "snippet": "Apply to 500+ TCS job openings.",
            },
        ],
    )

    resolution = DomainResolver.resolve("Tata Consultancy Services", search_res)
    assert resolution.state == DomainResolutionState.UNRESOLVED
    assert resolution.canonical_domain is None
    assert all("excluded" in r.get("reason", "").lower() for r in resolution.rejected_candidates)


# =============================================================================
# 9. Correct handling of www, case, trailing dots, paths, and ports
# =============================================================================

def test_normalization_handling():
    """Normalizes case, trailing dots, ports, and paths, while rejecting credentials and bad schemes."""
    parsed = DomainResolver.normalize_and_parse_url("HTTP://WWW.WIPRO.COM.:8080/careers/apply?ref=1#section")
    assert parsed.is_valid is True
    assert parsed.hostname == "www.wipro.com"
    assert parsed.registrable_domain == "wipro.com"
    assert parsed.sld == "wipro"
    assert parsed.normalized_url == "http://www.wipro.com:8080"

    # Reject credential-bearing URL
    cred_parsed = DomainResolver.normalize_and_parse_url("https://admin:secret@wipro.com")
    assert cred_parsed.is_valid is False
    assert cred_parsed.rejection_reason == "credential_bearing_url"

    # Reject unsupported scheme
    ftp_parsed = DomainResolver.normalize_and_parse_url("ftp://wipro.com/files")
    assert ftp_parsed.is_valid is False
    assert "unsupported_scheme" in ftp_parsed.rejection_reason


# =============================================================================
# 10. Multi-label public suffixes
# =============================================================================

def test_multi_label_public_suffixes():
    """Correctly handles multi-label public suffixes such as co.in, co.uk, com.au."""
    for raw_url, expected_reg, expected_sld in [
        ("https://careers.tcs.co.in", "tcs.co.in", "tcs"),
        ("https://www.wipro.co.uk/about", "wipro.co.uk", "wipro"),
        ("https://jobs.atlassian.com.au", "atlassian.com.au", "atlassian"),
        ("https://infy.org.in", "infy.org.in", "infy"),
    ]:
        parsed = DomainResolver.normalize_and_parse_url(raw_url)
        assert parsed.is_valid is True
        assert parsed.registrable_domain == expected_reg
        assert parsed.sld == expected_sld


# =============================================================================
# 11. Unicode/IDNA normalization without treating visual similarity as ownership
# =============================================================================

def test_unicode_and_idna_rejects_punycode_homoglyphs():
    """Punycode/IDNA visual homoglyphs (e.g. Cyrillic letters in Latin brand) must be rejected."""
    # "tсs.com" where 'с' is Cyrillic small letter es (U+0441)
    cyrillic_tcs = "https://xn--ts-pmc.com"
    parsed = DomainResolver.normalize_and_parse_url(cyrillic_tcs)
    assert parsed.is_valid is True  # Syntax normalization is separate from identity trust.
    result = DomainResolver.resolve("Tata Consultancy Services", SearchResult(
        query="TCS", knowledge_graph={"title": "Tata Consultancy Services", "website": cyrillic_tcs},
        results=[{"title": "Tata Consultancy Services", "link": cyrillic_tcs}]))
    assert result.state == DomainResolutionState.UNRESOLVED
    assert result.canonical_domain is None


# =============================================================================
# 12. Genuine subdomain alignment and deceptive hostname suffixes
# =============================================================================

def test_genuine_subdomain_alignment_and_deceptive_suffixes():
    """Genuine subdomains align, while deceptive suffixes on third-party domains fail."""
    # Genuine subdomain
    assert DomainResolver.is_matching_domain("hr.wipro.com", "wipro.com") is True
    assert DomainResolver.is_matching_domain("careers.wipro.com", "wipro.com") is True
    assert DomainResolver.is_matching_domain("recruitment@careers.wipro.com", "wipro.com") is False

    # Deceptive suffix
    assert DomainResolver.is_matching_domain("wipro.com.attacker.example", "wipro.com") is False
    assert DomainResolver.is_matching_domain("tcs-careers.example", "tcs.com") is False


# =============================================================================
# 13. Unrelated careers results
# =============================================================================

def test_unrelated_careers_results():
    """Unrelated results mentioning 'careers' in the title must not be accepted as careers URL."""
    search_res = SearchResult(
        query='"Wipro Limited" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        knowledge_graph={
            "title": "Wipro Limited",
            "website": "https://www.wipro.com",
        },
        results=[
            {
                "title": "Wipro: IT Services",
                "link": "https://www.wipro.com",
                "snippet": "Official website.",
            },
            {
                "title": "Careers at Top IT Firms - JobHunt",
                "link": "https://www.jobhunt-portal.example/careers",
                "snippet": "Find careers at Wipro and other companies.",
            },
        ],
    )

    resolution = DomainResolver.resolve("Wipro Limited", search_res)
    assert resolution.state == DomainResolutionState.RESOLVED
    assert resolution.canonical_domain == "www.wipro.com"
    # Unrelated careers link from jobhunt-portal must NOT be selected
    assert resolution.careers_url is None


# =============================================================================
# 14. Explicitly associated hosted careers pages
# =============================================================================

def test_explicitly_associated_hosted_careers_pages():
    """Hosted ATS platforms (Greenhouse, Workday) associate only when the company-aligned entity card links the exact tenant URL."""
    search_res = SearchResult(
        query='"Wipro Limited" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        knowledge_graph={
            "title": "Wipro Limited",
            "website": "https://www.wipro.com",
            "careers_url": "https://wipro.wd3.myworkdayjobs.com/careers",
        },
        results=[
            {
                "title": "Wipro",
                "link": "https://www.wipro.com",
                "snippet": "Official site.",
            },
            {
                "title": "Wipro Careers on Workday",
                "link": "https://wipro.wd3.myworkdayjobs.com/careers",
                "snippet": "Official job portal on Workday.",
            },
        ],
    )

    resolution = DomainResolver.resolve("Wipro Limited", search_res)
    assert resolution.state == DomainResolutionState.RESOLVED
    assert resolution.canonical_domain == "www.wipro.com"
    assert resolution.careers_url == "https://wipro.wd3.myworkdayjobs.com/careers"


# =============================================================================
# 15. Empty results and provider failure outcomes
# =============================================================================

@pytest.mark.parametrize("outcome,expected_state", [
    (SearchOutcome.ZERO_RESULTS, DomainResolutionState.UNRESOLVED),
    (SearchOutcome.TIMEOUT, DomainResolutionState.SEARCH_UNAVAILABLE),
    (SearchOutcome.RATE_LIMIT, DomainResolutionState.SEARCH_UNAVAILABLE),
    (SearchOutcome.AUTH_FAILURE, DomainResolutionState.SEARCH_UNAVAILABLE),
    (SearchOutcome.PROVIDER_FAILURE, DomainResolutionState.SEARCH_UNAVAILABLE),
])
def test_empty_results_and_provider_failure_outcomes(outcome, expected_state):
    """Empty searches and provider failures map to honest unverified states."""
    search_res = SearchResult(
        query="test query",
        outcome=outcome,
        source="REAL" if outcome == SearchOutcome.ZERO_RESULTS else "FAILED",
        error="Failure" if outcome != SearchOutcome.ZERO_RESULTS else None,
    )
    resolution = DomainResolver.resolve("Example Corp", search_res)
    assert resolution.state == expected_state
    assert resolution.canonical_domain is None


# =============================================================================
# 16. Demo/MOCK results cannot resolve live company ownership
# =============================================================================

def test_demo_and_mock_results_cannot_resolve_live_ownership():
    """Non-live results (DEMO / MOCK) must return SEARCH_UNAVAILABLE."""
    search_res = SearchResult(
        query='"Wipro Limited" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="DEMO",
        results=[
            {
                "title": "Wipro",
                "link": "https://www.wipro.com",
                "snippet": "Official site.",
            }
        ],
    )
    resolution = DomainResolver.resolve("Wipro Limited", search_res)
    assert resolution.state == DomainResolutionState.SEARCH_UNAVAILABLE
    assert resolution.canonical_domain is None


# =============================================================================
# 17. Consistent domain resolution in both CompanyAgent and RecruiterAgent
# =============================================================================

@pytest.mark.asyncio
async def test_consistent_domain_resolution_in_both_agents():
    """Both CompanyAgent and RecruiterAgent use the exact same DomainResolver policy."""
    search_res = SearchResult(
        query='"Wipro Limited" official website careers',
        outcome=SearchOutcome.SUCCESS,
        source="REAL",
        knowledge_graph={
            "title": "Wipro Limited",
            "website": "https://www.wipro.com",
        },
        results=[
            {
                "title": "Wipro",
                "link": "https://www.wipro.com",
                "snippet": "Official site.",
            }
        ],
    )

    client = MockSearch(search_res)
    company_finding = await CompanyAgent(search_client=client).investigate("Wipro Limited")
    recruiter_finding = await RecruiterAgent(search_client=client).investigate(
        company_name="Wipro Limited",
        recruiter_name="Pooja",
        recruiter_email="pooja@wipro.com",
        recruiter_phone=None,
    )

    assert company_finding.verdict == "VERIFIED"
    assert company_finding.details["official_domain"] == "https://www.wipro.com"
    assert company_finding.details["official_domain_resolved"] is True

    assert recruiter_finding.verdict == "VERIFIED"
    assert recruiter_finding.details["domain_match"] is True


# =============================================================================
# 18. Partial recruiter checks remain intact
# =============================================================================

@pytest.mark.asyncio
async def test_partial_recruiter_checks_intact():
    """When company domain search times out, phone scam hits are preserved with PARTIAL status."""
    class PartialClient:
        async def search(self, query: str, **kwargs):
            if "official website" in query:
                return SearchResult(query=query, outcome=SearchOutcome.TIMEOUT, error="Company search timed out")
            return SearchResult(
                query=query,
                outcome=SearchOutcome.SUCCESS,
                source="REAL",
                results=[{
                    "title": "Scam phone report 9876543210",
                    "snippet": "Victim reported fraud from 9876543210.",
                    "link": "https://complaints.example/scam/9876543210",
                }],
            )

    recruiter_agent = RecruiterAgent(search_client=PartialClient())
    finding = await recruiter_agent.investigate(
        company_name="Unknown Enterprise",
        recruiter_name="Scammer",
        recruiter_email="recruiter@unknown-domain.example",
        recruiter_phone="+919876543210",
    )

    assert finding.verdict == "HIGH_RISK"
    assert finding.details["phone_flagged"] is True
    assert finding.details["domain_match"] is None  # Unresolved due to outage
    assert finding.details["provider_status"] == "PARTIAL"
    assert finding.details["checks"]["company_domain"]["search_status"] == "TIMEOUT"
    assert finding.evidence[0].source_url == "https://complaints.example/scam/9876543210"
