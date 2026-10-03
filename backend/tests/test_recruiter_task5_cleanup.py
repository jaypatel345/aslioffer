"""Task 5 safety regressions: authority, contact identity and unavailable checks."""
import pytest
from unittest.mock import AsyncMock
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.search.serpapi_client import SearchResult, SearchOutcome


def results(items):
    return SearchResult(query="test", outcome=SearchOutcome.SUCCESS, source="REAL", results=items)


def item(link, text):
    return {"link": link, "title": "Directory", "snippet": text}


@pytest.mark.parametrize("email", ["a b@acme.com", ".a@acme.com", "a..b@acme.com", "a@acme.com/path"])
def test_invalid_email_is_unusable(email):
    assert not RecruiterAgent._validate_email(email)[0]


@pytest.mark.parametrize("text", ["+44 9876543210", "19876543210", "98765432100", "x9876543210"])
def test_phone_does_not_guess_country_or_match_substrings(text):
    assert not RecruiterAgent._find_exact_phone_match("9876543210", text)


def test_exact_email_boundaries():
    assert not RecruiterAgent._email_match("jane@acme.com", "jane@acme.com.evil")
    assert not RecruiterAgent._email_match("jane@acme.com", "otherjane@acme.com")
    assert RecruiterAgent._email_match("jane@acme.com", "Contact jane@acme.com.")


@pytest.mark.parametrize("link,text", [
    ("https://linkedin.com.evil/profile", "Jane Doe recruiter at Acme Corp"),
    ("https://evil.example/?next=linkedin.com", "Jane Doe recruiter at Acme Corp"),
    ("https://acme.com/team", "Jane Doe recruiter. otherjane@acme.com"),
    ("https://acme.com/team", "Jane Doe retired recruiter jane@acme.com"),
    ("https://acme.com/team", "Jane Doe works through sales jane@acme.com"),
])
def test_weak_or_misattributed_affiliation(link, text):
    status, _, _, strength = RecruiterAgent._evaluate_affiliation_evidence(
        results([item(link, text)]), "Jane Doe", "jane@acme.com", "Acme Corp", "acme.com")
    assert status != "SUPPORTED"
    assert strength != "strong_employer_published"


@pytest.mark.parametrize("link,text", [
    ("https://apex.com/clients", "Apex Staffing authorized recruitment partner of Acme"),
    ("https://news.example/partners", "Apex Staffing authorized recruitment partner of Acme"),
    ("https://acme.com/partners", "Apex Staffing is not an authorized recruitment partner"),
    ("https://acme.com/partners", "Apex Staffing is our software vendor"),
])
def test_authorization_requires_employer_recruitment_evidence(link, text):
    status, _, evidence, _ = RecruiterAgent._evaluate_agency_authorization(
        results([item(link, text)]), "Apex Staffing", "apex.com", "Acme", "acme.com")
    # An agency name containing 'staffing' must not supply recruitment context.
    assert status != "SUPPORTED"
    assert not evidence


@pytest.mark.asyncio
async def test_profile_alone_does_not_verify_and_failure_is_unavailable():
    async def search(query):
        if "official website" in query:
            return {"source": "REAL", "outcome": "SUCCESS", "knowledge_graph": {"title": "Acme Corp", "website": "https://acme.com"}, "organic_results": [item("https://acme.com", "Acme Corp official website")]}
        if "scam fraud" in query:
            return results([])
        return results([item("https://linkedin.com/in/jane", "Jane Doe recruiter at Acme Corp")])
    client = AsyncMock(); client.search.side_effect = search
    finding = await RecruiterAgent(client).investigate("Acme Corp", "Jane Doe", "jane@acme.com")
    assert finding.verdict == "CANNOT_VERIFY"
    assert finding.details["offer_authenticated"] is False
    client.search.side_effect = lambda query: SearchResult(query=query, outcome=SearchOutcome.TIMEOUT, error="timeout")
    finding = await RecruiterAgent(client).investigate("Acme Corp", "Jane Doe", "jane@acme.com")
    assert finding.details["recruiter_affiliation_status"] == "CHECK_UNAVAILABLE"

@pytest.mark.asyncio
async def test_implicit_agency_discovery_is_bounded_and_does_not_authorize():
    async def search(query):
        if "official website" in query:
            return {"source": "REAL", "outcome": "SUCCESS", "knowledge_graph": {"title": "Acme Corp", "website": "https://acme.com"}, "organic_results": [item("https://acme.com", "Acme Corp official website")]}
        if "staffing recruitment agency" in query:
            return {"source": "REAL", "outcome": "SUCCESS", "knowledge_graph": {"title": "Apex Staffing", "website": "https://apex.com"}, "organic_results": [item("https://apex.com", "Apex Staffing official recruitment agency")]}
        return results([])
    client = AsyncMock(); client.search.side_effect = search
    finding = await RecruiterAgent(client).investigate("Acme Corp", "Jane Doe", "jane@apex.com", "+1 415 555 1234")
    assert finding.details["is_agency"] is True
    assert finding.details["agency_name"] == "Apex Staffing"
    assert finding.details["agency_authorization_status"] == "UNCONFIRMED"
    assert finding.verdict == "NEEDS_REVIEW"
    assert client.search.await_count <= 5


@pytest.mark.asyncio
async def test_free_email_report_is_checked_without_transferring_other_contact_allegations():
    client = AsyncMock()
    client.search.return_value = results([item("https://reports.example/report", "Contact jane@gmail.com. Scam reported from other@gmail.com.")])
    finding = await RecruiterAgent(client).investigate("Acme", "Jane", "jane@gmail.com")
    assert "email_reports" in finding.details["checks"]
    assert not finding.details["email_flagged"]
    client.search.return_value = results([item("https://reports.example/report", "Scammed by jane@gmail.com who demanded a fee.")])
    finding = await RecruiterAgent(client).investigate("Acme", "Jane", "jane@gmail.com")
    assert finding.verdict == "HIGH_RISK"
