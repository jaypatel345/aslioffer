"""
A sender that claims a resolved employer but writes from another domain is CONTRADICTED,
citing the retrieved result that established the official domain. Offline fixtures only.
"""
import pytest

from app.schemas.contract import CaseInput, ClaimKind, ClaimStatus, EvidenceRelation, SourceType
from app.services.investigation.pipeline import investigate_case
from tests.investigation.test_task11_adaptive_planner import MockSearchClient

WEBSITE = {
    "status": "successful",
    "source": "REAL",
    "knowledge_graph": {"title": "Kestrel Systems", "website": "https://www.kestrelsystems.example"},
    "organic_results": [
        {"link": "https://www.kestrelsystems.example/", "title": "Kestrel Systems - Official Site",
         "snippet": "Kestrel Systems is an IT consulting company headquartered in Pune."},
        {"link": "https://www.linkedin.com/company/kestrel-systems", "title": "Kestrel Systems | LinkedIn",
         "snippet": "Kestrel Systems official website: https://www.kestrelsystems.example"},
    ],
}


def _case(sender_line):
    text = ("Offer Letter - Kestrel Systems\n"
            "Designation: Associate Consultant\n"
            f"{sender_line}\n")
    return CaseInput(case_id=1, run_id="run_sender", source_type=SourceType.TEXT, redacted_text=text)


def _sender(result):
    claim = next(c for c in result.claims if c.kind == ClaimKind.SENDER_EMAIL)
    return claim, next(a for a in result.assessed_claims if a.claim_id == claim.claim_id)


@pytest.mark.asyncio
async def test_webmail_sender_for_resolved_employer_is_contradicted():
    client = MockSearchClient(query_responses={"Kestrel Systems official website": WEBSITE})
    result = await investigate_case(_case("For queries, contact HR at kestrel.hr.desk@gmail.com"), search_client=client)

    employer = next(a for a in result.assessed_claims
                    if a.claim_id == next(c.claim_id for c in result.claims if c.kind == ClaimKind.EMPLOYER))
    assert employer.status == ClaimStatus.SUPPORTED
    claim, assessed = _sender(result)
    assert assessed.status == ClaimStatus.CONTRADICTED
    assert "SENDER_DOMAIN_MISMATCH" in assessed.reason_codes and "FREE_WEBMAIL_SENDER" in assessed.reason_codes
    assert "kestrelsystems.example" in assessed.explanation and "gmail.com" in assessed.explanation
    cited = [e for e in result.evidence if e.evidence_id in assessed.evidence_ids]
    assert cited and all(e.relation == EvidenceRelation.CONTRADICTS and e.claim_id == claim.claim_id for e in cited)
    assert all("kestrelsystems.example" in (e.source_url or "") for e in cited)


@pytest.mark.asyncio
async def test_sender_on_the_employers_own_domain_is_not_contradicted():
    client = MockSearchClient(query_responses={"Kestrel Systems official website": WEBSITE})
    result = await investigate_case(_case("For queries, contact HR at talent@kestrelsystems.example"), search_client=client)
    _, assessed = _sender(result)
    assert assessed.status != ClaimStatus.CONTRADICTED


@pytest.mark.asyncio
async def test_unresolved_employer_never_contradicts_the_sender():
    client = MockSearchClient(query_responses={})
    result = await investigate_case(_case("For queries, contact HR at kestrel.hr.desk@gmail.com"), search_client=client)
    _, assessed = _sender(result)
    assert assessed.status != ClaimStatus.CONTRADICTED
