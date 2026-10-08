"""
Employer-published recruiting addresses: found by a site-scoped search, accepted from the
employer's own recruitment section, and never mistaken for a fraud complaint when the
employer publishes them as the place to report fraud. All searches are fixtures.
"""
import pytest

from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.search.serpapi_client import SearchOutcome, SearchResult


def _res(query, items, kg=None):
    return SearchResult(query=query, outcome=SearchOutcome.SUCCESS, source="REAL",
                        results=items, knowledge_graph=kg or {})


class _Scripted:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    async def search(self, query, **kwargs):
        self.queries.append(query)
        return self.responses.get(query, _res(query, []))


ACN_WEBSITE = _res("Accenture official website", [
    {"link": "https://www.accenture.com/in-en", "title": "Accenture | Let there be change",
     "snippet": "Accenture is a leading global professional services company."},
], kg={"title": "Accenture", "website": "https://www.accenture.com"})


@pytest.mark.asyncio
async def test_email_affiliation_searches_the_employers_own_site():
    published = _res('site:accenture.com "candidate.queries@accenture.com"', [{
        "link": "https://acnrecruitment.accenture.com/help-content/candidatesupport.html",
        "title": "Accenture Video Interviews Technical Help",
        "snippet": "Alternatively, you can email your queries to candidate.queries@accenture.com.",
    }])
    client = _Scripted({ACN_WEBSITE.query: ACN_WEBSITE, published.query: published})
    finding = await RecruiterAgent(search_client=client).investigate(
        company_name="Accenture", recruiter_email="candidate.queries@accenture.com")

    assert published.query in client.queries
    assert finding.details["recruiter_affiliation_status"] == "SUPPORTED"


def test_recruitment_section_url_counts_but_other_sites_do_not():
    page = {"title": "Video Interviews Technical Help",
            "snippet": "Email your queries to candidate.queries@accenture.com."}
    own = _res("q", [dict(page, link="https://acnrecruitment.accenture.com/help")])
    other = _res("q", [dict(page, link="https://recruitment-help.example/accenture")])
    plain = _res("q", [dict(page, link="https://www.accenture.com/help")])
    evaluate = RecruiterAgent._evaluate_affiliation_evidence
    assert evaluate(own, None, "candidate.queries@accenture.com", "Accenture", "www.accenture.com")[0] == "SUPPORTED"
    assert evaluate(other, None, "candidate.queries@accenture.com", "Accenture", "www.accenture.com")[0] != "SUPPORTED"
    assert evaluate(plain, None, "candidate.queries@accenture.com", "Accenture", "www.accenture.com")[0] != "SUPPORTED"


@pytest.mark.parametrize("text", [
    "Recruitment Fraud Alert | Official Hiring Notice. Email id for contact - TalentEngagement@zensar.com",
    "... report suspected fraud: TalentEngagement@zensar.com At Zensar, Responsible Recruitment means ...",
    "Report suspected fraud to 1930 or write to careers@zensar.com",
])
def test_employer_fraud_reporting_notices_are_not_complaints(text):
    assert RecruiterAgent._evaluate_contact_adverse_context("", text)[0] is False


@pytest.mark.parametrize("text", [
    "Victim reported fraud from +919876543210.",
    "I was cheated by hr.tcs.jobs@gmail.com who demanded fee of 5000 for a laptop",
    "Fraud alert: fake recruiter tcs.hr@gmail.com demanded fee from students",
    "tcs.hr@gmail.com scam",
])
def test_real_complaints_are_still_flagged(text):
    assert RecruiterAgent._evaluate_contact_adverse_context("", text)[0] is True
