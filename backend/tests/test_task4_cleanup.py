"""Offline regressions for Task 4 URL, identity, ownership inference and ATS gaps."""
from unittest.mock import AsyncMock, patch

import pytest
import tldextract

from app.services.agents.company_agent import CompanyAgent
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.search import domain_resolver as module
from app.services.search.domain_resolver import DomainResolver as D, DomainResolutionState as State
from app.services.search.serpapi_client import SearchResult


def supported(name="Acme", url="https://acme.com", careers=None, extra=()):
    kg = {"title": name, "website": url}
    if careers:
        kg["careers_url"] = careers
    return SearchResult(query=name, knowledge_graph=kg, results=[{
        "title": name, "link": url, "snippet": f"{name} company website."}, *extra])


@pytest.mark.parametrize("url", [
    "https://wipro.com:bad", "https://wipro.com:99999", "https://[broken",
    "https://bad_host.com", "https://-bad.com", "https://bad-.com", "https://a..com",
    "https://wipro.com..", "https://wipro.com\\attacker.example", "https://127.0.0.1",
    "https://[::1]", "https://co.uk", "https://github.io", "https://user@wipro.com",
    "https://user:pass@wipro.com", "ftp://wipro.com", "javascript:alert(1)",
    "https://wipro.com/\npath", "https://" + "a" * 64 + ".com",
])
def test_malformed_or_non_corporate_url_never_crashes(url):
    parsed = D.normalize_and_parse_url(url)
    assert not parsed.is_valid
    result = D.resolve("Wipro", SearchResult(query="Wipro", knowledge_graph={"title": "Wipro", "website": url}))
    assert result.state != State.RESOLVED
    assert result.canonical_url is None


@pytest.mark.parametrize("url,host,reg", [
    ("//HR.WIPRO.CO.UK./careers", "hr.wipro.co.uk", "wipro.co.uk"),
    ("wipro.co.in:8443/careers", "wipro.co.in", "wipro.co.in"),
    ("https://one.github.io", "one.github.io", "one.github.io"),
    ("https://one.blogspot.com", "one.blogspot.com", "one.blogspot.com"),
    ("https://jobs.city.kawasaki.jp", "jobs.city.kawasaki.jp", "city.kawasaki.jp"),
    ("https://site.school.k12.ak.us", "site.school.k12.ak.us", "school.k12.ak.us"),
    ("https://brand.example", "brand.example", "brand.example"),
])
def test_complete_suffix_rules_and_protocol_relative_urls(url, host, reg):
    parsed = D.normalize_and_parse_url(url)
    assert parsed.is_valid
    assert parsed.hostname == host
    assert parsed.registrable_domain == reg


@pytest.mark.parametrize("email,canonical", [
    ("one.github.io", "two.github.io"), ("one.blogspot.com", "two.blogspot.com"),
    ("not a domain", "not a domain"), ("wipro.com:bad", "wipro.com:bad"),
    ("hr@wipro.com", "wipro.com"), ("wipro.com.attacker.example", "wipro.com"),
    ("wipro.com/path", "wipro.com"), ("wipro.com?ref=x", "wipro.com"),
])
def test_validation_precedes_email_domain_equality(email, canonical):
    assert D.is_matching_domain(email, canonical) is False


@pytest.mark.parametrize("email,canonical", [
    ("hr.wipro.co.in", "www.wipro.co.in"), ("WIPRO.COM.", "www.wipro.com"),
    ("hr.bücher.de", "xn--bcher-kva.de"),
])
def test_valid_email_domain_alignment(email, canonical):
    assert D.is_matching_domain(email, canonical) is True


def test_public_suffix_snapshot_requires_no_network_or_cache(monkeypatch):
    snapshot = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None,
        fallback_to_snapshot=True, include_psl_private_domains=True, extra_suffixes=("example",))
    monkeypatch.setattr(module, "_PSL", snapshot)
    with patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")) as request:
        assert D.normalize_and_parse_url("https://one.github.io").registrable_domain == "one.github.io"
        assert D.normalize_and_parse_url("https://www.city.kawasaki.jp").registrable_domain == "city.kawasaki.jp"
    request.assert_not_called()


def test_self_described_rank_one_result_is_a_candidate_not_ownership():
    result = D.resolve("Acme", SearchResult(query="Acme", results=[{
        "title": "Acme Official Website", "link": "https://acme.example", "snippet": "Acme official recruitment portal."}]))
    assert result.state == State.UNRESOLVED
    assert result.canonical_domain is None
    assert result.evidence == []
    assert result.diagnostics["candidate_domains"] == ["acme.example"]


def test_duplicate_self_described_pages_do_not_create_corroboration():
    result = D.resolve("Acme", SearchResult(query="Acme", results=[{
        "title": "Acme", "link": f"https://acme.example/page/{i}", "snippet": "Acme Official Website"} for i in range(5)]))
    assert result.state == State.UNRESOLVED
    assert result.canonical_url is None


def test_knowledge_graph_needs_company_identifying_organic_support():
    result = D.resolve("Acme", SearchResult(query="Acme", knowledge_graph={"title": "Acme", "website": "https://acme.com"}))
    assert result.state == State.UNRESOLVED
    assert result.canonical_url is None


@pytest.mark.parametrize("claimed,entity,url", [
    ("Apex Technologies", "Apex Tool Group", "https://apex.example"),
    ("Tata Consultancy Services", "Tata Motors", "https://tata.example"),
    ("Acme", "Acmeology", "https://acme.example"),
])
def test_partial_names_and_group_brands_do_not_validate_other_entities(claimed, entity, url):
    result = D.resolve(claimed, SearchResult(query=claimed,
        knowledge_graph={"title": entity, "website": url}, results=[{"title": entity, "link": url}]))
    assert result.state != State.RESOLVED
    assert result.canonical_url is None
    assert any(r["source"] == "knowledge_graph" for r in result.rejected_candidates)


def test_full_identity_entity_card_and_organic_result_still_resolve():
    result = D.resolve("Acme Limited", supported("Acme", "https://www.acme.com/about?source=search"))
    assert result.state == State.RESOLVED
    assert result.canonical_url == "https://www.acme.com"
    assert result.evidence[0]["source_url"] == "https://www.acme.com/about?source=search"
    assert result.diagnostics["same_domain_pages_are_independent"] is False


def test_brandless_domain_can_resolve_from_explicit_identity_evidence():
    result = D.resolve("Acme Ltd", supported("Acme", "https://parentcompany.example"))
    assert result.state == State.RESOLVED
    assert result.canonical_url == "https://parentcompany.example"


def test_explicit_external_website_reference_can_resolve_without_entity_card():
    result = D.resolve("Acme", SearchResult(query="Acme", results=[
        {"title": "Acme", "link": "https://acme.com", "snippet": "Acme company website."},
        {"title": "Acme company profile", "link": "https://www.linkedin.com/company/acme",
         "snippet": "Acme website: https://acme.com"},
    ]))
    assert result.state == State.RESOLVED
    assert result.canonical_url == "https://acme.com"
    assert result.diagnostics["independent_reference_hosts"] == 1
    assert any(e["source_url"].startswith("https://www.linkedin.com") for e in result.evidence)


def test_context_reference_to_unrelated_domain_does_not_corroborate():
    result = D.resolve("Acme", SearchResult(query="Acme", results=[
        {"title": "Acme", "link": "https://acme.com"},
        {"title": "Acme profile", "link": "https://www.linkedin.com/company/acme",
         "snippet": "Website: https://acme.org"},
    ]))
    assert result.state == State.UNRESOLVED


def test_entity_card_does_not_silently_override_conflicting_domain():
    result = D.resolve("Acme", supported(extra=[{"title": "Acme", "link": "https://acme.org", "snippet": "Acme website"}]))
    assert result.state == State.AMBIGUOUS
    assert result.canonical_url is None
    assert result.diagnostics["competing_domains"] == ["acme.com", "acme.org"]


def test_rank_one_and_duplicate_pages_do_not_override_later_competitor():
    results = [{"title": "Acme", "link": f"https://acme.com/{i}"} for i in range(4)]
    results.append({"title": "Acme", "link": "https://acme.org"})
    result = D.resolve("Acme", SearchResult(query="Acme", results=results))
    assert result.state == State.AMBIGUOUS
    assert result.canonical_url is None


def test_unicode_is_normalized_without_confusing_latin_and_cyrillic_names():
    assert D.normalize_and_parse_url("https://bücher.de").hostname == "xn--bcher-kva.de"
    result = D.resolve("Bücher", supported("Bücher", "https://bücher.de"))
    assert result.state == State.RESOLVED
    spoof = D.resolve("Tata Consultancy Services", supported("Tata Consultancy Services", "https://xn--ts-pmc.com"))
    assert spoof.state == State.UNRESOLVED


def test_ats_name_match_without_explicit_link_is_not_association():
    ats = {"title": "Acme careers", "link": "https://jobs.lever.co/acme", "snippet": "Acme jobs"}
    result = D.resolve("Acme", supported(extra=[ats]))
    assert result.state == State.RESOLVED
    assert result.careers_url is None


@pytest.mark.parametrize("relation", ["knowledge_graph", "company_snippet"])
def test_exact_hosted_tenant_link_is_supported(relation):
    ats_url = "https://jobs.lever.co/acme"
    ats = {"title": "Acme careers", "link": ats_url, "snippet": "Acme jobs"}
    search = supported(careers=ats_url if relation == "knowledge_graph" else None, extra=[ats])
    if relation == "company_snippet":
        search["organic_results"][0]["snippet"] = f"Acme careers: {ats_url}"
    result = D.resolve("Acme", search)
    assert result.careers_url == ats_url


def test_external_portal_title_and_other_tenant_do_not_establish_association():
    result = D.resolve("Acme", supported(careers="https://jobs.lever.co/other", extra=[{
        "title": "Acme careers", "link": "https://jobs.lever.co/acme", "snippet": "Acme jobs"}]))
    assert result.careers_url is None


def test_same_domain_article_containing_career_substring_is_not_a_careers_page():
    result = D.resolve("Acme", supported(extra=[{
        "title": "Acme company news", "link": "https://acme.com/news/careerism", "snippet": "Acme opinion article"}]))
    assert result.careers_url is None


@pytest.mark.asyncio
async def test_ambiguous_resolution_is_preserved_in_both_agents():
    search = supported(extra=[{"title": "Acme", "link": "https://acme.org"}])
    replay = type("Replay", (), {"search": AsyncMock(return_value=search)})()
    company = await CompanyAgent(replay).investigate("Acme")
    recruiter = await RecruiterAgent(replay).investigate("Acme", None, "hr@acme.com", None)
    assert company.verdict == recruiter.verdict == "CANNOT_VERIFY"
    assert company.details["resolution_state"] == "AMBIGUOUS"
    assert company.details["resolution_diagnostics"]["competing_domains"] == ["acme.com", "acme.org"]
    assert recruiter.details["domain_match"] is None
    assert recruiter.details["checks"]["company_domain"]["resolution_state"] == "AMBIGUOUS"


@pytest.mark.asyncio
async def test_bad_url_is_inconclusive_without_crashing_agents():
    search = supported(url="https://acme.com:bad")
    replay = type("Replay", (), {"search": AsyncMock(return_value=search)})()
    company = await CompanyAgent(replay).investigate("Acme")
    recruiter = await RecruiterAgent(replay).investigate("Acme", None, "hr@acme.com", None)
    assert company.verdict == recruiter.verdict == "CANNOT_VERIFY"
    assert company.evidence == recruiter.evidence == []
