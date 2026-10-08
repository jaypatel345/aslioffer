"""
Entity-card + search-dominance resolution for well-known employers whose search
entity card carries no website link (observed live for Infosys, TCS and Wipro).
Offline: every search result here is a fixture.
"""
import pytest

from app.services.agents.company_agent import CompanyAgent
from app.services.search.domain_resolver import (
    DomainResolver,
    DomainResolutionState,
    company_entity_query,
    company_website_query,
    resolve_employer_domain,
)
from app.services.search.serpapi_client import SearchOutcome, SearchResult


def _search(query, organic, knowledge_graph=None):
    return SearchResult(query=query, outcome=SearchOutcome.SUCCESS, source="REAL",
                        results=organic, knowledge_graph=knowledge_graph or {})


def _page(link, title="Infosys - Consulting | IT Services", snippet="Infosys is a global leader in digital services."):
    return {"link": link, "title": title, "snippet": snippet}


INFOSYS_WEBSITE = _search(company_website_query("Infosys Limited"), [
    _page("https://www.infosys.com/industries/communication-services/"),
    _page("https://www.infosys.com/services/applied-ai/"),
    _page("https://www.infosys.com/digital-outlook/"),
    _page("https://www.foundit.in/search/infosys-limited-jobs", "1682 Infosys Limited Jobs",
          "Apply to Infosys Limited jobs."),
    _page("https://www.infosys.com/careers/"),
    _page("https://hiringinstantly.in/companies/infosys-limited", "Infosys Limited — Jobs and Company Profile",
          "Infosys Limited jobs, careers and company profile."),
])

INFOSYS_ENTITY = _search(company_entity_query("Infosys Limited"), [
    _page("https://www.infosys.com/"),
    _page("https://in.linkedin.com/company/infosys", "Infosys | LinkedIn"),
    _page("https://en.wikipedia.org/wiki/Infosys", "Infosys - Wikipedia",
          "Infosys Limited is an Indian multinational technology company."),
], knowledge_graph={"title": "Infosys", "type": "IT services company"})


def test_website_search_alone_does_not_resolve_dominant_domain():
    """Ranking and repeated self-pages alone are still not enough."""
    result = DomainResolver.resolve("Infosys Limited", INFOSYS_WEBSITE)
    assert result.state != DomainResolutionState.RESOLVED


def test_entity_card_plus_dominance_resolves_well_known_employer():
    result = DomainResolver.resolve("Infosys Limited", INFOSYS_WEBSITE, INFOSYS_ENTITY)
    assert result.state == DomainResolutionState.RESOLVED
    assert result.canonical_domain == "www.infosys.com"
    assert result.careers_url == "https://www.infosys.com/careers/"
    assert result.diagnostics["resolution_method"] == "entity_card_and_search_dominance"
    # Job boards that merely mention the name are never evidence for the domain.
    assert all("infosys.com" in e["source_url"] for e in result.evidence)


def test_fake_company_dominating_its_own_name_without_entity_card_stays_unresolved():
    """A scammer can make their own site rank for a made-up name; they do not get an entity card."""
    website = _search(company_website_query("Zentrova Analytics"), [
        _page(f"https://zentrova.com/{p}", "Zentrova Analytics", "Zentrova Analytics careers and services.")
        for p in ("", "about", "careers", "contact")
    ])
    entity = _search(company_entity_query("Zentrova Analytics"),
                     [_page("https://zentrova.com/", "Zentrova Analytics", "Zentrova Analytics.")])
    result = DomainResolver.resolve("Zentrova Analytics", website, entity)
    assert result.state != DomainResolutionState.RESOLVED


def test_entity_card_for_a_different_company_does_not_resolve():
    entity = _search(INFOSYS_ENTITY.query, INFOSYS_ENTITY.results,
                     knowledge_graph={"title": "Infosys BPM", "type": "Company"})
    assert DomainResolver.resolve("Infosys Limited", INFOSYS_WEBSITE, entity).state != DomainResolutionState.RESOLVED


def test_entity_card_with_conflicting_website_does_not_resolve():
    entity = _search(INFOSYS_ENTITY.query, INFOSYS_ENTITY.results,
                     knowledge_graph={"title": "Infosys", "website": "https://www.infosys-global.example"})
    assert DomainResolver.resolve("Infosys Limited", INFOSYS_WEBSITE, entity).state != DomainResolutionState.RESOLVED


def test_second_brand_named_domain_in_top_five_blocks_dominance():
    """infosys.com vs infosys.co near the top: two brand-named domains stay unresolved."""
    results = list(INFOSYS_WEBSITE.results)
    results.insert(1, _page("https://www.infosys.co/offer"))
    website = _search(INFOSYS_WEBSITE.query, results)
    assert DomainResolver.dominant_brand_domain("Infosys Limited", website) is None
    assert DomainResolver.resolve("Infosys Limited", website, INFOSYS_ENTITY).state != DomainResolutionState.RESOLVED


def test_lower_ranked_parent_brand_site_does_not_block_dominance():
    """Observed live: tata.com (Tata group) at rank 9 under tcs.com; 'tata' is also a brand word."""
    website = _search(company_website_query("Tata Consultancy Services"), [
        _page("https://www.tcs.com/what-we-do", "Connect business operations | TCS", "TCS helps you turn AI into a partner."),
        _page("https://www.instagram.com/tcsglobal/", "Tata Consultancy Services (@tcsglobal)"),
        _page("https://www.tcs.com/careers/india/tcs-launchpad", "TCS Launchpad", "TCS Launchpad careers."),
        _page("https://www.tcs.com/investor-relations", "Corporate Governance | TCS", "TCS board of directors."),
        _page("https://www.gesi.org/member/tcs/", "Tata Consultancy Services (TCS) - GeSI"),
        _page("https://www.tcs.com/careers/india/tcs-atlas-hiring", "TCS Atlas Hiring 2026"),
        _page("https://www.tcs.com/fr-fr/", "Tata Consultancy Services"),
        _page("https://www.tcs.com/careers/india/tcs-esu-hiring", "TCS ESU Hiring"),
        _page("https://www.tata.com/home-page", "The Tata group", "The official website for the Tata group."),
    ])
    entity = _search(company_entity_query("Tata Consultancy Services"), [
        _page("https://www.linkedin.com/company/tata-consultancy-services", "Tata Consultancy Services | LinkedIn"),
    ], knowledge_graph={"title": "Tata Consultancy Services", "type": "IT services company"})
    assert DomainResolver.dominant_brand_domain("Tata Consultancy Services", website)[0] == "tcs.com"
    result = DomainResolver.resolve("Tata Consultancy Services", website, entity)
    assert result.state == DomainResolutionState.RESOLVED
    assert result.canonical_domain == "www.tcs.com"


def test_brand_named_domain_in_entity_results_blocks_resolution():
    entity = _search(INFOSYS_ENTITY.query, INFOSYS_ENTITY.results + [_page("https://infosys.co/careers")],
                     knowledge_graph=INFOSYS_ENTITY.knowledge_graph)
    assert DomainResolver.resolve("Infosys Limited", INFOSYS_WEBSITE, entity).state != DomainResolutionState.RESOLVED


def test_dominance_requires_top_rank_and_majority_of_top_five():
    not_top = _search(INFOSYS_WEBSITE.query, [INFOSYS_WEBSITE.results[3]] + INFOSYS_WEBSITE.results[:3])
    assert DomainResolver.dominant_brand_domain("Infosys Limited", not_top) is None
    only_top = _search(INFOSYS_WEBSITE.query, [
        INFOSYS_WEBSITE.results[0], INFOSYS_WEBSITE.results[3], INFOSYS_WEBSITE.results[5],
        _page("https://www.naukri.com/infosys-jobs", "Infosys Jobs"),
        _page("https://en.wikipedia.org/wiki/Infosys", "Infosys - Wikipedia"),
        INFOSYS_WEBSITE.results[1],
    ])
    assert DomainResolver.dominant_brand_domain("Infosys Limited", only_top) is None
    # Observed live for Accenture: own site at #1 and #2, noise below, is enough to qualify.
    top_two = _search(INFOSYS_WEBSITE.query, INFOSYS_WEBSITE.results[:2] + INFOSYS_WEBSITE.results[3:4])
    assert DomainResolver.dominant_brand_domain("Infosys Limited", top_two)[0] == "infosys.com"


def test_lookalike_portal_domain_never_counts_as_brand_domain():
    website = _search("x", [_page(f"https://infosys-careers.in/{p}") for p in ("", "a", "b", "c")])
    assert DomainResolver.dominant_brand_domain("Infosys Limited", website) is None


class _ScriptedSearch:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    async def search(self, query, **kwargs):
        self.queries.append(query)
        return self.responses.get(query, _search(query, []))


@pytest.mark.asyncio
async def test_entity_search_only_runs_when_a_domain_dominates():
    client = _ScriptedSearch({INFOSYS_WEBSITE.query: INFOSYS_WEBSITE, INFOSYS_ENTITY.query: INFOSYS_ENTITY})
    _, resolution, entity = await resolve_employer_domain(client, "Infosys Limited")
    assert resolution.state == DomainResolutionState.RESOLVED
    assert entity is not None
    assert client.queries == [company_website_query("Infosys Limited"), company_entity_query("Infosys Limited")]

    sparse = _ScriptedSearch({})
    _, resolution, entity = await resolve_employer_domain(sparse, "Coorix Labs")
    assert resolution.state != DomainResolutionState.RESOLVED
    assert entity is None
    assert sparse.queries == [company_website_query("Coorix Labs")]


@pytest.mark.asyncio
async def test_company_agent_reports_resolved_well_known_employer():
    client = _ScriptedSearch({INFOSYS_WEBSITE.query: INFOSYS_WEBSITE, INFOSYS_ENTITY.query: INFOSYS_ENTITY})
    finding = await CompanyAgent(search_client=client).investigate("Infosys Limited")
    assert finding.verdict == "VERIFIED"
    assert finding.details["canonical_domain"] == "www.infosys.com"
    assert finding.details["official_domain_resolved"] is True
