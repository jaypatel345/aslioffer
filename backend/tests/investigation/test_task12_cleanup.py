"""Adversarial Task 12 checks for attributable jobs, honest coverage and routes."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.schemas.contract import (CaseInput, Claim, ClaimKind, ClaimStatus, EventStatus,
    EvidenceRelation, ExtractionStatus, RetrievalStatus, SourceKind, SourceTier, SourceType)
from app.services.investigation.assessor import ClaimAssessor
from app.services.investigation.budget import InvestigationBudget
from app.services.investigation.corroborator import (CorroborationObservation,
    JobCorroborationResult, JobCorroborationService, evaluate_application_destination,
    generate_confirmation_draft, is_public_job_reference)
from app.services.investigation.evidence_adapter import EvidenceAdapter
from app.services.investigation.pipeline import investigate_case
from app.services.investigation.planner import InvestigationPlanner

NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
HOST = "acme.example"
URL = "https://acme.example/jobs/engineer"


def claim(kind, value, source_quote=None):
    return Claim(claim_id=kind.value, kind=kind, value=value,
                 source_quote=source_quote or value, extraction_status=ExtractionStatus.EXTRACTED)


def metadata(url=URL, title="Software Engineer - Acme Careers",
             snippet="We are hiring a Software Engineer in Bengaluru. Apply online.",
             status=RetrievalStatus.LIVE, step="resolve_employer_domain"):
    return dict(source_url=url, title=title, snippet=snippet, retrieval_status=status,
                query='"Acme" official website careers', engine="google", search_id="search-1",
                retrieved_at=NOW, step=step)


def corroborate(claims, metas=(), steps=(), **kwargs):
    snippets = {}
    for m in metas:
        snippets.setdefault(m["source_url"], []).append(m)
    return JobCorroborationService().corroborate(claims=claims, company_name="Acme",
        canonical_domain=HOST, snippets_by_url=snippets, executed_steps=set(steps), **kwargs)


def adapt(claims, metas, result):
    snippets = {}
    for m in metas:
        snippets.setdefault(m["source_url"], []).append(m)
    recorder = SimpleNamespace(snippets_by_url=snippets, tool_calls=[], failed_searches=[])
    return EvidenceAdapter().adapt_evidence(claims, {}, recorder, [], HOST, result)


@pytest.mark.parametrize("role,title,snippet", [
    ("Senior Software Engineer", "Software Engineer", "Hiring a Software Engineer."),
    ("Software Engineer", "Software Engineer Intern", "Hiring a Software Engineer Intern."),
    ("Software Engineer", "Software Engineering Manager", "Hiring a Software Engineering Manager."),
    ("Software Engineer", "Software Engineer", "This position is closed; applications closed."),
    ("Software Engineer", "Software Engineer", "We are not hiring for this role."),
    ("Software Engineer", "Software Engineer", "This vacancy has expired."),
])
def test_role_rejects_level_substring_and_closed_matches(role, title, snippet):
    c = claim(ClaimKind.ROLE, role)
    result = corroborate([c], [metadata(title=title, snippet=snippet)],
                         ["adaptive_job_role_corroboration"])
    assert result.observations[c.claim_id].status == ClaimStatus.UNRESOLVED
    assert not result.observations[c.claim_id].evidence_items


@pytest.mark.parametrize("status", [RetrievalStatus.FAILED, RetrievalStatus.DEMO, None])
def test_non_live_observations_cannot_corroborate_job_or_destination(status):
    claims = [claim(ClaimKind.ROLE, "Software Engineer"), claim(ClaimKind.APPLICATION_URL, URL)]
    result = corroborate(claims, [metadata(status=status)])
    assert all(o.status == ClaimStatus.NOT_CHECKED for o in result.observations.values())
    assert not result.executed_checks


@pytest.mark.parametrize("url,text", [
    ("https://unrelated.example/jobs/1", "Job requisition REQ-123: Software Engineer"),
    (URL, "Job requisition REQ-1234: Software Engineer"),
    (URL, "Job requisition XREQ-123: Software Engineer"),
    (URL, "Job requisition REQ-123-A: Software Engineer"),
    (URL, "Requisition REQ-123: position filled, no longer accepting applications"),
])
def test_requisition_requires_exact_attributable_open_record(url, text):
    c = claim(ClaimKind.JOB_REFERENCE, "REQ-123")
    result = corroborate([c], [metadata(url=url, snippet=text)], ["adaptive_job_reference_corroboration"])
    assert result.observations[c.claim_id].status == ClaimStatus.UNRESOLVED


@pytest.mark.parametrize("reference", ["123456", "ID-123456", "REF-123456", "AB-123456"])
def test_ambiguous_identifiers_are_not_public_queries(reference):
    assert not is_public_job_reference(reference)[0]


def test_private_context_overrides_public_looking_reference_in_plan_and_draft():
    claims = [claim(ClaimKind.EMPLOYER, "Acme"), claim(ClaimKind.ROLE, "Software Engineer"),
              claim(ClaimKind.JOB_REFERENCE, "REQ-123", "Candidate reference: REQ-123")]
    plan = InvestigationPlanner().create_plan(claims, {}, set(), canonical_domain=HOST)
    assert not any(s.strategy == "JOB_REFERENCE_CORROBORATION" for s in plan)
    result = corroborate(claims, [metadata(snippet="For offer verification contact verify@acme.example.")])
    assert result.observations[ClaimKind.JOB_REFERENCE.value].status == ClaimStatus.NOT_CHECKED
    assert "REQ-123" not in result.confirmation_route.draft_message


def test_headquarters_in_matching_vacancy_is_not_job_location():
    claims = [claim(ClaimKind.ROLE, "Software Engineer"), claim(ClaimKind.LOCATION, "Bengaluru")]
    result = corroborate(claims, [metadata(title="Software Engineer - Mumbai",
        snippet="We are hiring a Software Engineer in Mumbai. Acme is headquartered in Bengaluru.")])
    assert result.observations[ClaimKind.ROLE.value].status == ClaimStatus.SUPPORTED
    assert result.observations[ClaimKind.LOCATION.value].status == ClaimStatus.UNRESOLVED


def test_location_can_match_second_relevant_vacancy_and_is_order_independent():
    claims = [claim(ClaimKind.ROLE, "Software Engineer"), claim(ClaimKind.LOCATION, "Bengaluru")]
    first = metadata(url="https://acme.example/jobs/a", snippet="Hiring a Software Engineer in Mumbai.")
    second = metadata(url="https://acme.example/jobs/b", snippet="Hiring a Software Engineer in Bengaluru.")
    a = corroborate(claims, [first, second])
    b = corroborate(claims, [second, first])
    assert a.observations == b.observations
    assert a.observations[ClaimKind.LOCATION.value].status == ClaimStatus.SUPPORTED


def test_ats_name_and_search_result_without_employer_publication_abstains():
    ats = "https://acme.wd3.myworkdayjobs.com/careers/job-1"
    claims = [claim(ClaimKind.ROLE, "Software Engineer"), claim(ClaimKind.APPLICATION_URL, ats)]
    result = corroborate(claims, [metadata(url=ats)], careers_url=ats.rsplit("/", 1)[0])
    assert all(o.status != ClaimStatus.SUPPORTED for o in result.observations.values())
    assert result.confirmation_route is None
    direct = evaluate_application_destination(ats, "Acme", HOST, {ats})
    assert direct["status"] == ClaimStatus.UNRESOLVED


def test_published_ats_association_preserves_third_party_tier():
    portal = "https://acme.wd3.myworkdayjobs.com/careers"
    ats = portal + "/job-1"
    claims = [claim(ClaimKind.EMPLOYER, "Acme"), claim(ClaimKind.ROLE, "Software Engineer"),
              claim(ClaimKind.LOCATION, "Bengaluru"), claim(ClaimKind.APPLICATION_URL, ats)]
    metas = [metadata(url="https://acme.example", title="Acme", snippet=f'Acme careers: {portal}'), metadata(url=ats)]
    result = corroborate(claims, metas, careers_url=portal)
    records = adapt(claims, metas, result)
    assert result.observations[ClaimKind.APPLICATION_URL.value].status == ClaimStatus.SUPPORTED
    for kind in (ClaimKind.ROLE, ClaimKind.LOCATION, ClaimKind.APPLICATION_URL):
        assert any(e.claim_id == kind.value and e.source_tier == SourceTier.ESTABLISHED_THIRD_PARTY for e in records)


@pytest.mark.parametrize("snippet", [
    "Never contact careers@acme.example for recruitment verification.",
    "Avoid unauthorized careers@acme.example for hiring.",
    "Contact shruti@acme.example for recruitment verification.",
    "Recruitment office information. Contact sales@acme.example for purchases.",
])
def test_route_rejects_negative_unrelated_and_personal_mailboxes(snippet):
    result = corroborate([claim(ClaimKind.EMPLOYER, "Acme")], [metadata(snippet=snippet)])
    assert result.confirmation_route is None


def test_unobserved_careers_url_is_not_a_route():
    result = corroborate([claim(ClaimKind.EMPLOYER, "Acme")], careers_url="https://acme.example/careers")
    assert result.confirmation_route is None


def test_adapter_binds_exact_snippet_and_does_not_invent_document_support():
    claims = [claim(ClaimKind.EMPLOYER, "Acme"), claim(ClaimKind.ROLE, "Software Engineer")]
    correct = metadata(snippet="Hiring a Software Engineer. Contact verify@acme.example for offer verification.")
    unrelated = metadata(title="Acme company home", snippet="Office information.")
    result = corroborate(claims, [unrelated, correct])
    records = adapt(claims, [unrelated, correct], result)
    job = [e for e in records if e.claim_id == ClaimKind.ROLE.value]
    assert len(job) == 1 and job[0].quote_or_snippet == correct["snippet"]
    route_record = next(e for e in records if e.evidence_id == result.confirmation_route.evidence_id)
    assert route_record.quote_or_snippet == correct["snippet"]
    assert route_record.source_kind == SourceKind.SEARCH_SNIPPET
    assert route_record.query == correct["query"] and route_record.search_id == "search-1"
    fabricated = JobCorroborationResult(observations={claims[1].claim_id: CorroborationObservation(
        claims[1].claim_id, ClaimKind.ROLE, ClaimStatus.SUPPORTED, ["ROLE_CORROBORATED"], "Matched vacancy",
        [{"source_url": "https://acme.example/invented", "description": "Invented match", "relation": EvidenceRelation.SUPPORTS}])})
    assert not adapt(claims, [], fabricated)
    assessed = ClaimAssessor().assess_claims(claims, [], {}, [], corroboration_result=fabricated)
    role = next(a for a in assessed if a.claim_id == ClaimKind.ROLE.value)
    assert role.status == ClaimStatus.UNRESOLVED
    assert role.reason_codes == ["NO_ATTRIBUTABLE_CITATION"]
    assert "Matched vacancy" not in role.explanation


def test_partial_outage_does_not_erase_completed_corroboration():
    c = claim(ClaimKind.ROLE, "Software Engineer")
    meta = metadata()
    result = corroborate([c], [meta])
    records = adapt([c], [meta], result)
    assessed = ClaimAssessor().assess_claims([c], records, {}, [], provider_outage=True, corroboration_result=result)
    assert assessed[0].status == ClaimStatus.SUPPORTED


def test_failed_targeted_search_remains_unresolved_but_does_not_count_completed():
    c = claim(ClaimKind.ROLE, "Software Engineer")
    recording = SimpleNamespace(snippets_by_url={}, tool_calls=[SimpleNamespace(
        step="adaptive_job_role_corroboration", status=EventStatus.FAILED)])
    result = JobCorroborationService().corroborate([c], company_name="Acme", canonical_domain=HOST, recording_client=recording)
    assert result.observations[c.claim_id].reason_codes == ["SEARCH_UNAVAILABLE"]
    assert ClaimKind.ROLE in result.failed_checks
    assert ClaimKind.ROLE not in result.executed_checks


@pytest.mark.asyncio
async def test_budget_denied_jobs_do_not_inflate_checked_coverage():
    class Search:
        async def search(self, **kwargs):
            return {"status": "successful", "source": "REAL", "knowledge_graph":
                    {"title": "Acme Systems Ltd", "website": "https://acme.example"}, "organic_results": []}
    case = CaseInput(case_id=12001, run_id="task12_budget", source_type=SourceType.TEXT,
        redacted_text="Offer from Acme Systems Ltd.\nPosition: Software Engineer\nLocation: Bengaluru\nJob Reference: REQ-123")
    result = await investigate_case(case, search_client=Search(), budget=InvestigationBudget(max_search_calls=1, max_followup_calls=0))
    for c in result.claims:
        if c.kind in (ClaimKind.ROLE, ClaimKind.LOCATION, ClaimKind.JOB_REFERENCE):
            assert next(a for a in result.assessed_claims if a.claim_id == c.claim_id).status == ClaimStatus.NOT_CHECKED
    assert result.coverage.checked_claims == 1


def test_drafts_and_url_diagnostics_do_not_echo_private_values():
    draft = generate_confirmation_draft("official_email", "Acme", "Engineer\npassword: secret123", "OFFER/2026/491", "otp: 123456")
    assert all(s not in draft for s in ("secret123", "123456", "OFFER/2026/491"))
    assert "[Position / Role Title]" in draft
    evaluation = evaluate_application_destination("https://admin:secret123@acme.example/apply", "Acme", HOST, set())
    assert "secret123" not in evaluation["explanation"]


def test_phone_route_requires_adjacent_published_contact_label():
    employer = claim(ClaimKind.EMPLOYER, "Acme")
    bad = metadata(snippet="Requisition 9876543210. Recruitment office details are available elsewhere.")
    assert corroborate([employer], [bad]).confirmation_route is None
    good = metadata(snippet="Recruitment office: +91 9876543210 for offer verification.")
    result = corroborate([employer], [good])
    assert result.confirmation_route.channel == "official_phone"
    assert result.confirmation_route.destination == "+91 9876543210"


def test_unsafe_document_url_citation_redacts_embedded_credentials():
    value = "https://admin:secret123@acme.example/apply"
    c = claim(ClaimKind.APPLICATION_URL, value, "Application link: " + value)
    result = corroborate([c])
    records = adapt([c], [], result)
    assert len(records) == 1
    assert records[0].source_kind == SourceKind.DOCUMENT
    assert records[0].relation == EvidenceRelation.CONTRADICTS
    assert "secret123" not in records[0].quote_or_snippet


def test_biography_and_incidental_city_do_not_support_hiring_claims():
    role = claim(ClaimKind.ROLE, "Software Engineer")
    biography = metadata(url="https://acme.example/careers/stories", title="Software Engineer",
                         snippet="Our colleague is a Software Engineer. Read her career story.")
    assert corroborate([role], [biography]).observations[role.claim_id].status != ClaimStatus.SUPPORTED
    city = claim(ClaimKind.LOCATION, "Bengaluru")
    vacancy = metadata(title="Software Engineer - Mumbai", snippet="Hiring a Software Engineer in Mumbai. Customers are in Bengaluru.")
    assert corroborate([role, city], [vacancy]).observations[city.claim_id].status == ClaimStatus.UNRESOLVED


def test_signed_observation_cannot_become_a_confirmation_route():
    url = "https://acme.example/careers?token=private123"
    result = corroborate([claim(ClaimKind.EMPLOYER, "Acme")], [metadata(url=url)], careers_url=url)
    assert result.confirmation_route is None
