"""
Real-world wording seen in live tests: employer named only in the title line, fee
demands with extra words ("training kit deposit"), and offers with no employer name.
"""
import pytest

from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.agents.scam_classifier import ScamClassifier
from app.services.extractor.grounded_parser import GroundedEntityParser
from app.services.search.serpapi_client import SearchOutcome, SearchResult


def _employer(text):
    claims = GroundedEntityParser().parse(text, source_type="text").claims
    return next(c for c in claims if c.kind.value == "claimed_employer").value


@pytest.mark.parametrize("title, expected", [
    ("Offer Letter - Capgemini India", "Capgemini India"),
    ("Offer of Employment - HCLTech", "HCLTech"),
    ("Appointment Letter: L&T Technology Services", "L&T Technology Services"),
    ("Offer Letter - Congratulations!", None),
    ("Offer Letter - Welcome Aboard", None),
])
def test_employer_from_offer_title_line(title, expected):
    assert _employer(f"{title}\nDesignation: Analyst Trainee\nDear Candidate, you are selected.") == expected


def _codes(text):
    return {(str(a.signal_code), str(a.modality)) for a in ScamClassifier().classify(text)}


@pytest.mark.parametrize("text", [
    "Pay a refundable training kit deposit of INR 6,000 via UPI to capg.onboard@paytm to confirm.",
    "Kindly pay the joining processing fee of Rs 2,500 before Monday.",
    "Pay Rs 999 for your employee ID card charge via GPay.",
])
def test_fee_demands_with_extra_words_are_upfront_fees(text):
    assert ("UPFRONT_FEE_DEMAND", "active_demand") in _codes(text)


def test_negated_kit_deposit_is_still_a_policy():
    assert _codes("We never charge any training kit deposit or joining fee.") == {("NEGATED_FEE_POLICY", "negated_policy")}


class _Recording:
    def __init__(self):
        self.queries = []

    async def search(self, query, **kwargs):
        self.queries.append(query)
        return SearchResult(query=query, outcome=SearchOutcome.SUCCESS, source="REAL", results=[])


@pytest.mark.asyncio
async def test_no_employer_means_no_employer_searches():
    client = _Recording()
    await RecruiterAgent(search_client=client).investigate(
        company_name="", recruiter_email="capgemini.onboarding.hr@gmail.com")
    assert not any("official website" in q for q in client.queries)
    assert not any(q.endswith('""') for q in client.queries)
