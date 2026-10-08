"""
Community "scam or legit?" threads for little-known employers, and employer names given
only as a sender team ("From: Coorix HR"). Offline fixtures only.
"""
import pytest

from app.services.agents.scam_agent import ScamAgent
from app.services.extractor.grounded_parser import GroundedEntityParser
from app.services.search.serpapi_client import SearchOutcome, SearchResult


class _Scripted:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    async def search(self, query, **kwargs):
        self.queries.append(query)
        return self.responses.get(query, SearchResult(query=query, outcome=SearchOutcome.SUCCESS, source="REAL", results=[]))


THREAD = {
    "link": "https://www.reddit.com/r/PlacementsPrep/comments/abc/coorix_internship_scam_or_legit/",
    "title": "Coorix Internship — Scam or Legit? : r/PlacementsPrep",
    "snippet": "Hey everyone, did anyone else get an email regarding the Coorix internship?",
}
QUERY = '"Coorix" internship scam or legit'
TEXT = "From: Coorix HR\nThank you for your interest in the Coorix Internship Drive. Screening round today."


def _client():
    return _Scripted({QUERY: SearchResult(query=QUERY, outcome=SearchOutcome.SUCCESS, source="REAL", results=[THREAD])})


@pytest.mark.asyncio
async def test_discussion_thread_is_surfaced_for_unresolved_employer():
    client = _client()
    finding = await ScamAgent(search_client=client).investigate(
        company_name="Coorix", demanded_fee=None, payment_method=None, flags=[], raw_text=TEXT)
    assert QUERY in client.queries
    assert finding.details["public_discussions"] == [{"url": THREAD["link"], "title": THREAD["title"]}]
    # A question thread is a caution, never a scam report, and never raises the verdict.
    assert all(e.evidence_type != "SCAM_REPORT" for e in finding.evidence)
    assert finding.verdict != "HIGH_RISK"


@pytest.mark.asyncio
async def test_no_discussion_search_for_resolved_employer():
    client = _client()
    finding = await ScamAgent(search_client=client).investigate(
        company_name="Coorix", demanded_fee=None, payment_method=None, flags=[], raw_text=TEXT,
        employer_resolved=True)
    assert QUERY not in client.queries
    assert finding.details["public_discussions"] == []


def test_job_boards_and_unrelated_threads_are_not_discussions():
    assert not ScamAgent._public_discussion("Coorix", "https://internshala.com/x", "Coorix scam or legit", "")
    assert not ScamAgent._public_discussion("Coorix", "https://www.reddit.com/r/x", "Job application scam?", "Another company")
    assert ScamAgent._public_discussion("Coorix", THREAD["link"], THREAD["title"], THREAD["snippet"])


def test_sender_team_names_the_employer_when_repeated():
    claims = GroundedEntityParser().parse(TEXT, source_type="text").claims
    assert next(c for c in claims if c.kind.value == "claimed_employer").value == "Coorix"


@pytest.mark.parametrize("text", [
    "From: Selection Committee\nDear Applicant, the Selection Process begins today.",
    "From: Google Meet Team\nJoin the call on Google Meet.",
    "From: Coorix HR\nPlease join the screening round today.",  # named only once
])
def test_sender_team_is_not_an_employer_without_corroboration(text):
    claims = GroundedEntityParser().parse(text, source_type="text").claims
    assert next(c for c in claims if c.kind.value == "claimed_employer").value is None
