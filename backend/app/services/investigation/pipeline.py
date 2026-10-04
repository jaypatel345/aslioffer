"""
Unified investigation pipeline entry point for AsliOffer (Task 10).

Executes a single investigation run without database or HTTP dependencies.
Produces valid contract-v1 InvestigationResult objects.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.schemas.contract import (
    CaseInput,
    ConfirmationRoute,
    EventStatus,
    InvestigationResult,
    OverallOutcome,
    RunError,
    RunEvent,
    SourceTier,
    ClaimKind,
)
from app.services.agents.company_agent import CompanyAgent
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.agents.salary_agent import SalaryAgent
from app.services.agents.scam_agent import ScamAgent
from app.services.risk.assessment_engine import AssessmentEngine
from app.services.report.presentation_helper import derive_recommended_actions
from app.services.investigation.assessor import ClaimAssessor
from app.services.investigation.claim_builder import ClaimBuilder, is_redaction_placeholder
from app.services.investigation.coverage import compute_coverage
from app.services.investigation.events import EventEmitter
from app.services.investigation.evidence_adapter import EvidenceAdapter
from app.services.investigation.recording_search import RecordingSearchClient
from app.core.logging import logger


async def investigate_case(
    case_input: CaseInput,
    search_client: Optional[Any] = None,
    emit_event: Optional[Callable[[RunEvent], Any]] = None,
) -> InvestigationResult:
    """
    Executes one isolated investigation run from CaseInput and returns an InvestigationResult.

    Parameters:
        case_input: Grounded case parameters including redacted document text and confirmed claims.
        search_client: Injected search client (or mock) for reproducible execution.
        emit_event: Optional async callback for streaming RunEvent updates.
    """
    events = EventEmitter(run_id=case_input.run_id, emit_fn=emit_event)
    recording_client = RecordingSearchClient(underlying_client=search_client, demo_mode=case_input.demo_mode)
    errors: List[RunError] = []

    # 1. Claim extraction stage
    await events.emit("extract_claims", EventStatus.STARTED, "Extracting offer claims from document text")
    builder = ClaimBuilder()
    try:
        claims, scam_assessments, ext_result = builder.build_claims(case_input)
        await events.emit("extract_claims", EventStatus.COMPLETED, f"Extracted {len(claims)} document claims")
    except Exception as exc:
        logger.error("Claim extraction failed: %s", exc)
        await events.emit("extract_claims", EventStatus.FAILED, "Claim extraction encountered an error")
        raise

    # Identify primary claims
    emp_claim = next((c for c in claims if c.kind == ClaimKind.EMPLOYER), None)
    email_claim = next((c for c in claims if c.kind == ClaimKind.SENDER_EMAIL), None)
    phone_claim = next((c for c in claims if c.kind == ClaimKind.CONTACT_PHONE), None)
    rec_name_claim = next((c for c in claims if c.kind == ClaimKind.RECRUITER_NAME), None)
    sal_claim = next((c for c in claims if c.kind == ClaimKind.COMPENSATION), None)
    role_claim = next((c for c in claims if c.kind == ClaimKind.ROLE), None)

    company_name = emp_claim.value if (emp_claim and emp_claim.value and not is_redaction_placeholder(emp_claim.value)) else None
    recruiter_email = email_claim.value if (email_claim and email_claim.value and not is_redaction_placeholder(email_claim.value)) else None
    recruiter_phone = phone_claim.value if (phone_claim and phone_claim.value and not is_redaction_placeholder(phone_claim.value)) else None
    recruiter_name = rec_name_claim.value if (rec_name_claim and rec_name_claim.value and not is_redaction_placeholder(rec_name_claim.value)) else None
    role_title = role_claim.value if (role_claim and role_claim.value and not is_redaction_placeholder(role_claim.value)) else None
    offered_salary = sal_claim.value if (sal_claim and sal_claim.value and not is_redaction_placeholder(sal_claim.value)) else None

    # Initialize agents sharing the recording search client
    comp_agent = CompanyAgent(search_client=recording_client)
    rec_agent = RecruiterAgent(search_client=recording_client)
    sal_agent = SalaryAgent(search_client=recording_client)
    scam_agent = ScamAgent(search_client=recording_client)

    finding_comp = None
    finding_rec = None
    finding_sal = None
    finding_scam = None

    canonical_domain: Optional[str] = None
    careers_url: Optional[str] = None
    provider_outage = False

    # 2. Company domain resolution stage (sequenced first to resolve official domain)
    if company_name:
        await events.emit("resolve_company", EventStatus.STARTED, f"Resolving employer footprint for '{company_name}'")
        try:
            with recording_client.step("resolve_employer_domain", "Resolve the employer's official domain before checking contact details"):
                finding_comp = await comp_agent.investigate(company_name)

            if finding_comp.details.get("provider_status") == "FAILED" or finding_comp.details.get("resolution_state") == "SEARCH_UNAVAILABLE":
                provider_outage = True
                await events.emit("resolve_company", EventStatus.FAILED, "Search provider unavailable for employer resolution")
                errors.append(
                    RunError(
                        code="SEARCH_PROVIDER_OUTAGE",
                        message="Search provider request timed out or was unavailable",
                        step="resolve_company",
                        retryable=True,
                    )
                )
            else:
                canonical_domain = finding_comp.details.get("canonical_domain") or finding_comp.details.get("official_domain")
                if canonical_domain and "://" in canonical_domain:
                    from urllib.parse import urlparse
                    canonical_domain = urlparse(canonical_domain).hostname or canonical_domain
                careers_url = finding_comp.details.get("careers_url")
                await events.emit("resolve_company", EventStatus.COMPLETED, f"Employer resolution finished: domain={canonical_domain or 'unresolved'}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("CompanyAgent failed: %s", exc)
            errors.append(
                RunError(
                    code="COMPANY_INVESTIGATION_ERROR",
                    message="Unexpected error during employer domain resolution",
                    step="resolve_company",
                    retryable=False,
                )
            )
            await events.emit("resolve_company", EventStatus.FAILED, "Employer resolution encountered an error")
    else:
        await events.emit("resolve_company", EventStatus.SKIPPED, "No valid employer name to resolve")

    # 3. Concurrent downstream checks (Recruiter, Salary, Scam)
    has_recruiter_contact = bool(recruiter_email or recruiter_phone or recruiter_name)
    has_salary_claim = bool(offered_salary)

    async def run_recruiter():
        if not company_name and not has_recruiter_contact:
            await events.emit("check_recruiter", EventStatus.SKIPPED, "No recruiter contacts to check")
            return None
        if not has_recruiter_contact:
            await events.emit("check_recruiter", EventStatus.SKIPPED, "Recruiter contact details are missing or redacted")
            return None
        await events.emit("check_recruiter", EventStatus.STARTED, "Checking recruiter email and affiliation")
        with recording_client.step("check_recruiter_contact", "Verify recruiter email alignment with resolved domain"):
            return await rec_agent.investigate(
                company_name=company_name or "Unknown Company",
                recruiter_name=recruiter_name,
                recruiter_email=recruiter_email,
                recruiter_phone=recruiter_phone,
            )

    async def run_salary():
        if not has_salary_claim or not company_name:
            await events.emit("check_compensation", EventStatus.SKIPPED, "No compensation or employer to benchmark")
            return None
        await events.emit("check_compensation", EventStatus.STARTED, "Checking market compensation benchmarks")
        with recording_client.step("check_compensation_benchmark", "Look for market salary baselines"):
            return await sal_agent.investigate(
                company_name=company_name,
                role_title=role_title,
                offered_salary=offered_salary,
            )

    async def run_scam():
        await events.emit("check_scam_signals", EventStatus.STARTED, "Analyzing document text and scam signals")
        with recording_client.step("check_scam_signals", "Check for upfront fees, credential demands, and adverse reports"):
            return await scam_agent.investigate(
                company_name=company_name or "Unknown Company",
                demanded_fee=ext_result.to_extracted_data().payment_amount,
                payment_method=ext_result.to_extracted_data().payment_method,
                flags=ext_result.to_extracted_data().flags,
                raw_text=case_input.redacted_text,
            )

    tasks = [
        asyncio.create_task(run_recruiter()),
        asyncio.create_task(run_salary()),
        asyncio.create_task(run_scam()),
    ]

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        raise

    # Unpack results and isolate individual failures
    for idx, (res, step_name) in enumerate(zip(results, ["check_recruiter", "check_compensation", "check_scam_signals"])):
        if isinstance(res, asyncio.CancelledError):
            raise res
        elif isinstance(res, Exception):
            logger.error("Agent %s failed with exception: %s", step_name, res)
            errors.append(
                RunError(
                    code="AGENT_CHECK_FAILURE",
                    message="Investigation check encountered an isolated failure",
                    step=step_name,
                    retryable=False,
                )
            )
            await events.emit(step_name, EventStatus.FAILED, f"Investigation step '{step_name}' failed")
        else:
            if idx == 0:
                finding_rec = res
                if res:
                    await events.emit("check_recruiter", EventStatus.COMPLETED, "Recruiter check completed")
            elif idx == 1:
                finding_sal = res
                if res:
                    await events.emit("check_compensation", EventStatus.COMPLETED, "Compensation check completed")
            elif idx == 2:
                finding_scam = res
                if res:
                    await events.emit("check_scam_signals", EventStatus.COMPLETED, "Scam signal assessment completed")

    # 4. Synthesize findings using AssessmentEngine (Task 8 policy)
    await events.emit("assess_verdict", EventStatus.STARTED, "Computing unified assessment policy")
    active_findings = [f for f in [finding_comp, finding_rec, finding_sal, finding_scam] if f is not None]

    assessment_engine = AssessmentEngine()
    structured_assessment = assessment_engine.assess(active_findings)
    overall_outcome = structured_assessment.overall_outcome

    # 5. Adapt Evidence
    findings_map = {
        "CompanyAgent": finding_comp,
        "RecruiterAgent": finding_rec,
        "SalaryAgent": finding_sal,
        "ScamAgent": finding_scam,
    }
    evidence_adapter = EvidenceAdapter(demo_mode=case_input.demo_mode)
    evidence_records = evidence_adapter.adapt_evidence(
        claims=claims,
        findings=findings_map,
        recording_client=recording_client,
        scam_assessments=scam_assessments,
        canonical_employer_domain=canonical_domain,
    )

    # 6. Assess Claims
    assessor = ClaimAssessor()
    assessed_claims = assessor.assess_claims(
        claims=claims,
        evidence_records=evidence_records,
        findings=findings_map,
        scam_assessments=scam_assessments,
        canonical_employer_domain=canonical_domain,
        provider_outage=provider_outage,
    )

    # 7. Grounded Recommended Actions
    actions = derive_recommended_actions(structured_assessment)
    # Ensure standard universal recommendations exist
    if overall_outcome == OverallOutcome.HIGH_RISK:
        if not any("do not" in a.lower() for a in actions):
            actions.insert(0, "Do not pay any fee, deposit, or share banking OTPs.")
    elif overall_outcome == OverallOutcome.CANNOT_VERIFY:
        if provider_outage:
            actions.insert(0, "Re-run this investigation once the search provider is available.")
            actions.append("Do not pay any fee or share bank OTPs.")
        else:
            actions.insert(0, "Ask the company for an official website or LinkedIn page and a contact you can reach independently.")
            actions.append("Do not pay any fee or share bank OTPs at any stage.")
    elif overall_outcome == OverallOutcome.NO_STRONG_RISK_SIGNALS:
        actions.insert(0, f"No strong risk signals were found, but only {company_name or 'the employer'} can confirm this offer.")
        actions.append("Accept the offer through the careers portal you reach yourself, not through a link in an email.")

    # Deduplicate actions preserving order
    deduped_actions: List[str] = []
    seen_act = set()
    for a in actions:
        if a not in seen_act:
            seen_act.add(a)
            deduped_actions.append(a)

    # 8. Confirmation Route
    # Only if independently sourced, employer-published channel exists in evidence
    confirmation_route: Optional[ConfirmationRoute] = None
    if careers_url and canonical_domain:
        matching_ev = next(
            (e for e in evidence_records if e.source_tier == SourceTier.OFFICIAL_EMPLOYER and e.source_url and canonical_domain in e.source_url.lower()),
            None,
        )
        if matching_ev:
            confirmation_route = ConfirmationRoute(
                channel="careers_portal",
                destination=careers_url,
                evidence_id=matching_ev.evidence_id,
                draft_message=None,
            )

    # 9. Tool Trace
    tool_trace = recording_client.tool_calls

    # 10. Coverage
    distinct_failed_checks = len(errors) + len(recording_client.failed_searches)
    coverage = compute_coverage(
        claims=claims,
        assessed_claims=assessed_claims,
        failed_check_count=distinct_failed_checks,
    )

    result = InvestigationResult(
        contract_version=case_input.contract_version,
        run_id=case_input.run_id,
        demo_mode=case_input.demo_mode,
        claims=claims,
        assessed_claims=assessed_claims,
        evidence=evidence_records,
        overall_outcome=overall_outcome,
        authenticity_status=structured_assessment.authenticity_status,
        coverage=coverage,
        recommended_actions=deduped_actions,
        confirmation_route=confirmation_route,
        tool_trace=tool_trace,
        errors=errors,
    )

    await events.emit("assess_verdict", EventStatus.COMPLETED, f"Investigation complete: outcome={overall_outcome.value}")
    return result
