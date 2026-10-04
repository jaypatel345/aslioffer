"""
Unified investigation pipeline entry point for AsliOffer (Task 10).

Executes a single investigation run without database or HTTP dependencies.
Produces valid contract-v1 InvestigationResult objects.
"""

import asyncio
import re
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
    ClaimStatus,
    ExtractionStatus,
    CONTRACT_VERSION,
)
from app.services.agents.company_agent import CompanyAgent
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.agents.salary_agent import SalaryAgent
from app.services.agents.scam_agent import ScamAgent
from app.services.risk.assessment_engine import AssessmentEngine
from app.services.report.presentation_helper import derive_recommended_actions
from app.schemas.analysis import EvidenceItem
from app.services.investigation.assessor import ClaimAssessor
from app.services.investigation.budget import BudgetManager, InvestigationBudget
from app.services.investigation.claim_builder import ClaimBuilder, is_redaction_placeholder
from app.services.investigation.coverage import compute_coverage
from app.services.investigation.events import EventEmitter
from app.services.investigation.evidence_adapter import EvidenceAdapter
from app.services.investigation.planner import InvestigationPlanner, PlanStep
from app.services.investigation.recording_search import RecordingSearchClient
from app.services.investigation.corroborator import JobCorroborationService
from app.services.search.serpapi_client import SearchResult
from app.services.search.domain_resolver import DomainResolver, DomainResolutionState
from app.core.logging import logger


async def investigate_case(
    case_input: CaseInput,
    search_client: Optional[Any] = None,
    emit_event: Optional[Callable[[RunEvent], Any]] = None,
    budget: Optional[InvestigationBudget] = None,
) -> InvestigationResult:
    """
    Executes one isolated investigation run from CaseInput and returns an InvestigationResult.

    Parameters:
        case_input: Grounded case parameters including redacted document text and confirmed claims.
        search_client: Injected search client (or mock) for reproducible execution.
        emit_event: Optional async callback for streaming RunEvent updates.
        budget: Optional InvestigationBudget configuring call limits, follow-up limits, and deadlines.
    """
    if case_input.contract_version != CONTRACT_VERSION:
        raise ValueError("Unsupported investigation contract version")
    budget_manager = BudgetManager(budget=budget)
    events = EventEmitter(run_id=case_input.run_id, emit_fn=emit_event)
    recording_client = RecordingSearchClient(
        underlying_client=search_client,
        demo_mode=case_input.demo_mode,
        budget_manager=budget_manager,
    )
    errors: List[RunError] = []

    # 1. Claim extraction stage
    await events.emit("extract_claims", EventStatus.STARTED, "Extracting offer claims from document text")
    builder = ClaimBuilder()
    try:
        claims, scam_assessments, ext_result = builder.build_claims(case_input)
        await events.emit("extract_claims", EventStatus.COMPLETED, f"Extracted {len(claims)} document claims")
    except Exception as exc:
        logger.error("Claim extraction failed")
        await events.emit("extract_claims", EventStatus.FAILED, "Claim extraction encountered an error")
        raise

    # Identify primary claims
    emp_claim = next((c for c in claims if c.kind == ClaimKind.EMPLOYER), None)
    email_claim = next((c for c in claims if c.kind == ClaimKind.SENDER_EMAIL), None)
    phone_claim = next((c for c in claims if c.kind == ClaimKind.CONTACT_PHONE), None)
    rec_name_claim = next((c for c in claims if c.kind == ClaimKind.RECRUITER_NAME), None)
    sal_claim = next((c for c in claims if c.kind == ClaimKind.COMPENSATION), None)
    role_claim = next((c for c in claims if c.kind == ClaimKind.ROLE), None)

    company_name = emp_claim.value if (emp_claim and emp_claim.extraction_status != ExtractionStatus.UNCERTAIN and emp_claim.value and not is_redaction_placeholder(emp_claim.value)) else None
    recruiter_email = email_claim.value if (email_claim and email_claim.extraction_status != ExtractionStatus.UNCERTAIN and email_claim.value and not is_redaction_placeholder(email_claim.value)) else None
    recruiter_phone = phone_claim.value if (phone_claim and phone_claim.extraction_status != ExtractionStatus.UNCERTAIN and phone_claim.value and not is_redaction_placeholder(phone_claim.value)) else None
    recruiter_name = rec_name_claim.value if (rec_name_claim and rec_name_claim.extraction_status != ExtractionStatus.UNCERTAIN and rec_name_claim.value and not is_redaction_placeholder(rec_name_claim.value)) else None
    role_title = role_claim.value if (role_claim and role_claim.extraction_status != ExtractionStatus.UNCERTAIN and role_claim.value and not is_redaction_placeholder(role_claim.value)) else None
    offered_salary = sal_claim.value if (sal_claim and sal_claim.extraction_status != ExtractionStatus.UNCERTAIN and sal_claim.value and not is_redaction_placeholder(sal_claim.value)) else None

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
        await events.emit("resolve_company", EventStatus.STARTED, "Resolving the claimed employer public footprint")
        try:
            with recording_client.step("resolve_employer_domain", "Resolve the employer's official domain before checking contact details"):
                finding_comp = await comp_agent.investigate(company_name)

            if finding_comp.details.get("provider_status") == "FAILED" or finding_comp.details.get("resolution_state") == "SEARCH_UNAVAILABLE":
                denied = any(d["step"] == "resolve_employer_domain" for d in budget_manager.denied_calls)
                if denied and not any(f["step"] == "resolve_employer_domain" for f in recording_client.failed_searches):
                    await events.emit("resolve_company", EventStatus.SKIPPED, "Employer search skipped by investigation admission limits")
                else:
                    provider_outage = True
                    await events.emit("resolve_company", EventStatus.FAILED, "Search provider unavailable for employer resolution")
                    errors.append(
                        RunError(
                            code="SEARCH_PROVIDER_OUTAGE",
                            message="Search provider request timed out or was unavailable",
                            step="resolve_employer_domain",
                            retryable=True,
                        )
                    )
            else:
                canonical_domain = finding_comp.details.get("canonical_domain") or finding_comp.details.get("official_domain")
                if canonical_domain and "://" in canonical_domain:
                    from urllib.parse import urlparse
                    canonical_domain = urlparse(canonical_domain).hostname or canonical_domain
                careers_url = finding_comp.details.get("careers_url")
                await events.emit("resolve_company", EventStatus.COMPLETED, "Employer domain resolution finished")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("CompanyAgent failed")
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
                company_name=company_name or "",
                recruiter_name=recruiter_name,
                recruiter_email=recruiter_email,
                recruiter_phone=recruiter_phone,
            )

    essential_done = asyncio.Event()
    essential_remaining = 2

    async def run_salary():
        await essential_done.wait()
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
        if not company_name:
            from app.services.search.serpapi_client import SearchResult, SearchOutcome
            class LocalOnlySearch:
                async def search(self, query, **kwargs):
                    return SearchResult(query=query, outcome=SearchOutcome.PROVIDER_FAILURE,
                                        error="Employer absent; external scam search not executed")
            local_finding = await ScamAgent(search_client=LocalOnlySearch()).investigate(
                company_name="", demanded_fee=None, payment_method=None, flags=[], raw_text=case_input.redacted_text)
            local_finding.details.update(provider_status="NOT_CHECKED", search_status="NOT_CHECKED",
                                         error=None, checks={})
            await events.emit("external_scam_search", EventStatus.SKIPPED, "Employer absent; external scam search not executed")
            return local_finding
        with recording_client.step("check_scam_signals", "Check for upfront fees, credential demands, and adverse reports"):
            return await scam_agent.investigate(
                company_name=company_name or "",
                demanded_fee=ext_result.to_extracted_data().payment_amount,
                payment_method=ext_result.to_extracted_data().payment_method,
                flags=ext_result.to_extracted_data().flags,
                raw_text=case_input.redacted_text,
            )

    async def finish_step(fn, name):
        nonlocal essential_remaining
        try:
            result = await fn()
            if result is not None:
                failed = result.details.get("provider_status") in ("FAILED", "PARTIAL")
                await events.emit(name, EventStatus.FAILED if failed else EventStatus.COMPLETED,
                                  "Check retained partial results; external retrieval was unavailable" if failed else "Check completed")
            return result
        finally:
            if name in ("check_recruiter", "check_scam_signals"):
                essential_remaining -= 1
                if essential_remaining == 0:
                    essential_done.set()

    tasks = [
        asyncio.create_task(finish_step(run_recruiter, "check_recruiter")),
        asyncio.create_task(finish_step(run_salary, "check_compensation")),
        asyncio.create_task(finish_step(run_scam, "check_scam_signals")),
    ]

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    # Unpack results and isolate individual failures
    for idx, (res, step_name) in enumerate(zip(results, ["check_recruiter", "check_compensation", "check_scam_signals"])):
        if isinstance(res, asyncio.CancelledError):
            raise res
        elif isinstance(res, Exception):
            logger.error("Agent %s failed", step_name)
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

            elif idx == 1:
                finding_sal = res

            elif idx == 2:
                finding_scam = res


    if finding_sal and finding_sal.verdict == "VERIFIED":
        finding_sal = finding_sal.model_copy(update={"verdict": "CANNOT_VERIFY", "confidence": 0.0,
            "summary": "No comparable market compensation data was established.",
            "details": {**finding_sal.details, "anomaly": None, "benchmark_range": None}})

    # Surface every failed external retrieval, including downstream failures.
    recorded_steps = {e.step for e in errors if e.code == "SEARCH_PROVIDER_OUTAGE"}
    for failure in recording_client.failed_searches:
        if failure["step"] not in recorded_steps:
            errors.append(RunError(code="SEARCH_CHECK_UNAVAILABLE", message="An external retrieval was unavailable",
                                   step=failure["step"], retryable=True))
            recorded_steps.add(failure["step"])

    # 3.5 Adaptive Planning Stage (Task 11)
    # Examines initial unresolved/conflicting findings and executes bounded follow-ups.
    await events.emit("plan_investigation", EventStatus.STARTED, "Evaluating adaptive investigation plan")
    planner = InvestigationPlanner()
    executed_queries = {c.query.lower() for c in recording_client.tool_calls if c.query}

    current_findings = {
        "CompanyAgent": finding_comp,
        "RecruiterAgent": finding_rec,
        "SalaryAgent": finding_sal,
        "ScamAgent": finding_scam,
    }

    plan_steps: List[PlanStep] = []
    if not provider_outage and not budget_manager.auth_failure_detected and not budget_manager.is_deadline_exceeded:
        plan_steps = planner.create_plan(
            claims=claims,
            findings=current_findings,
            executed_queries=executed_queries,
            canonical_domain=canonical_domain,
            case_input=case_input,
            careers_url=careers_url,
        )

    if not plan_steps:
        await events.emit("plan_investigation", EventStatus.SKIPPED, "No productive follow-up checks required")
    else:
        executed_followups = 0
        attempted_queries = set(executed_queries)
        while plan_steps:
            step = plan_steps.pop(0)
            if step.query.lower() in attempted_queries:
                continue
            attempted_queries.add(step.query.lower())
            if budget_manager.is_deadline_exceeded or budget_manager.auth_failure_detected:
                break

            step_name = f"adaptive_{step.strategy.lower()}"
            await events.emit(step_name, EventStatus.STARTED, step.rationale)
            try:
                with recording_client.step(step_name, step.rationale):
                    raw_res = await recording_client.search(step.query)
                search_res = SearchResult.from_dict_or_result(raw_res, query=step.query)
                if raw_res.get("budget_denied"):
                    search_res.update(budget_denied=True, denial_type=raw_res.get("denial_type"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Adaptive step %s failed", step_name)
                await events.emit(step_name, EventStatus.FAILED, f"Adaptive search failed for step {step_name}")
                continue

            if search_res.get("budget_denied"):
                await events.emit(step_name, EventStatus.SKIPPED, f"Adaptive check skipped: {search_res.get("denial_type", "investigation limit")}")
                break

            if not search_res.is_live:
                await events.emit(step_name, EventStatus.FAILED, "Adaptive search returned no usable results or provider error")
                continue

            executed_followups += 1
            await events.emit(step_name, EventStatus.COMPLETED, f"Adaptive search completed for {step_name}")

            # Merge follow-up evidence into active findings
            if step.strategy == "EMPLOYER_CONTEXT" and company_name:
                resolution = DomainResolver.resolve(company_name, search_res)
                if resolution.state == DomainResolutionState.RESOLVED and resolution.canonical_domain:
                    canonical_domain = resolution.canonical_domain
                    careers_url = resolution.careers_url
                    if finding_comp:
                        finding_comp.details.update({
                            "official_domain_resolved": True,
                            "canonical_domain": resolution.canonical_domain,
                            "official_domain": resolution.canonical_url,
                            "careers_url": resolution.careers_url,
                            "resolution_state": resolution.state.value,
                            "resolution_basis": resolution.basis,
                        })
                        finding_comp.verdict = "VERIFIED"
                        for item in resolution.evidence:
                            finding_comp.evidence.append(EvidenceItem(
                                source_url=item["source_url"],
                                title=item.get("title", f"{company_name} Official Domain"),
                                description=item.get("description", ""),
                                evidence_type="COMPANY",
                                confidence=item.get("confidence", resolution.confidence),
                            ))
                    # Domain alignment is one dimension, not recruiter authentication.
                    if recruiter_email and finding_rec:
                        email_domain = recruiter_email.split("@")[-1].lower().strip()
                        aligned = DomainResolver.is_matching_domain(email_domain, resolution.canonical_domain)
                        finding_rec.details["domain_match"] = aligned
                        dimensions = finding_rec.details.setdefault("assessment_dimensions", {})
                        dimensions.setdefault("employer_domain_resolution", {}).update(status="SUPPORTED", source_urls=[e.source_url for e in finding_comp.evidence])
                        dimensions.setdefault("recruiter_email_domain", {}).update(status="SUPPORTED" if aligned else "CONFLICTING", domain_match=aligned)
                        # Preserve adverse reports, agency uncertainty and unavailable checks.
                        if finding_rec.verdict != "HIGH_RISK":
                            finding_rec.verdict = "NEEDS_REVIEW" if not aligned else "CANNOT_VERIFY"
                        finding_rec.details.pop("reason_code", None) if aligned and finding_rec.details.get("reason_code") == "RECRUITER_DOMAIN_MISMATCH" else None
                    if finding_rec:
                        aff_status, aff_expl, aff_ev, aff_str = rec_agent._evaluate_affiliation_evidence(
                            search_res, recruiter_name, recruiter_email, company_name, canonical_domain)
                        if aff_status == "SUPPORTED":
                            finding_rec.details.update(recruiter_affiliation_status=aff_status,
                                recruiter_affiliation_strength=aff_str)
                            finding_rec.details.setdefault("assessment_dimensions", {}).setdefault("recruiter_affiliation", {}).update(
                                status=aff_status, evidence_strength=aff_str, source_urls=[e.source_url for e in aff_ev], explanation=aff_expl)
                            finding_rec.evidence.extend(aff_ev)
                    current_findings["CompanyAgent"] = finding_comp
                    current_findings["RecruiterAgent"] = finding_rec
                    plan_steps = planner.create_plan(claims, current_findings, attempted_queries,
                                                     canonical_domain, case_input, careers_url)

            elif step.strategy == "AGENCY_AUTHORIZATION" and finding_rec:
                agency_name = (
                    finding_rec.details.get("assessment_dimensions", {}).get("agency_identity", {}).get("raw_facts", {}).get("agency_name")
                    or finding_rec.details.get("agency_identity_facts", {}).get("agency_name")
                    or finding_rec.details.get("agency_name")
                    or (recruiter_email.split("@")[-1] if recruiter_email else "")
                )
                agency_domain = finding_rec.details.get("agency_domain") or finding_rec.details.get("assessment_dimensions", {}).get("agency_identity", {}).get("raw_facts", {}).get("canonical_domain")
                auth_status, auth_expl, auth_ev, auth_str = rec_agent._evaluate_agency_authorization(
                    search_res, agency_name, agency_domain, company_name or "", canonical_domain
                )
                if auth_status == "SUPPORTED":
                    finding_rec.details["agency_authorization_status"] = "SUPPORTED"
                    finding_rec.details["agency_authorization_expl"] = auth_expl
                    finding_rec.details["agency_authorization_strength"] = auth_str
                    finding_rec.details.setdefault("assessment_dimensions", {}).setdefault("agency_authorization", {}).update(
                        status="SUPPORTED", evidence_strength=auth_str, explanation=auth_expl,
                        source_urls=[e.source_url for e in auth_ev])
                    for ev in auth_ev:
                        finding_rec.evidence.append(ev)

            elif step.strategy == "RECRUITER_AFFILIATION" and finding_rec:
                aff_status, aff_expl, aff_ev, aff_str = rec_agent._evaluate_affiliation_evidence(
                    search_res, recruiter_name, recruiter_email, company_name or "", canonical_domain
                )
                if aff_status == "SUPPORTED":
                    finding_rec.details["recruiter_affiliation_status"] = "SUPPORTED"
                    finding_rec.details["recruiter_affiliation_expl"] = aff_expl
                    finding_rec.details["recruiter_affiliation_strength"] = aff_str
                    finding_rec.details.setdefault("assessment_dimensions", {}).setdefault("recruiter_affiliation", {}).update(
                        status="SUPPORTED", evidence_strength=aff_str, explanation=aff_expl,
                        source_urls=[e.source_url for e in aff_ev])
                    for ev in aff_ev:
                        finding_rec.evidence.append(ev)

            elif step.strategy == "RECRUITMENT_FEE_POLICY" and finding_scam:
                for item in search_res.organic_results or []:
                    link = item.get("link", "")
                    parsed = DomainResolver.normalize_and_parse_url(link)
                    if parsed.is_valid and canonical_domain and DomainResolver.is_matching_domain(parsed.hostname, canonical_domain):
                        text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
                        if re.search(r"\b(?:never\s+(?:ask|charge)|do\s+not\s+(?:ask|charge)|no\s+(?:recruitment\s+)?fees?|free recruitment)\b", text):
                            finding_scam.evidence.append(EvidenceItem(
                                source_url=link,
                                title=item.get("title") or "Recruitment policy search observation",
                                description=item.get("snippet") or "",
                                evidence_type="SCAM",
                                confidence=0.90,
                            ))
                            break

        await events.emit("plan_investigation", EventStatus.COMPLETED, f"Adaptive investigation completed {executed_followups} follow-up checks")

    recorded_failure_steps = {e.step for e in errors}
    for failure in recording_client.failed_searches:
        if failure["step"] not in recorded_failure_steps:
            errors.append(RunError(code="SEARCH_CHECK_UNAVAILABLE", message="External retrieval unavailable; partial evidence retained",
                                   step=failure["step"], retryable=True))
            recorded_failure_steps.add(failure["step"])

    for denial in budget_manager.denied_calls:
        await events.emit(denial["step"], EventStatus.SKIPPED, f"External check skipped: {denial['type']}")

    # Record budget or deadline errors
    if budget_manager.is_deadline_exceeded:
        errors.append(
            RunError(
                code="INVESTIGATION_DEADLINE_EXCEEDED",
                message="Investigation external elapsed deadline expired; partial findings retained",
                step="external_investigation",
                retryable=True,
            )
        )
    if budget_manager.denied_calls:
        if any(d["type"] in ("BUDGET_EXCEEDED", "FOLLOWUP_BUDGET_EXCEEDED") for d in budget_manager.denied_calls):
            if not any(e.code == "INVESTIGATION_BUDGET_EXCEEDED" for e in errors):
                errors.append(
                    RunError(
                        code="INVESTIGATION_BUDGET_EXCEEDED",
                        message="Investigation search budget reached; remaining checks left unverified",
                        step="search_budget_gate",
                        retryable=False,
                    )
                )

    # 4. Synthesize findings using AssessmentEngine (Task 8 policy)
    await events.emit("assess_verdict", EventStatus.STARTED, "Computing unified assessment policy")
    active_findings = [f for f in [finding_comp, finding_rec, finding_sal, finding_scam] if f is not None]

    assessment_engine = AssessmentEngine()
    structured_assessment = assessment_engine.assess(active_findings)
    overall_outcome = structured_assessment.overall_outcome

    # 4.5 Corroborate Job and Application Claims (Task 12)
    corroborator = JobCorroborationService(demo_mode=case_input.demo_mode)
    corroboration_res = corroborator.corroborate(
        claims=claims,
        findings=current_findings,
        recording_client=recording_client,
        canonical_domain=canonical_domain,
        careers_url=careers_url,
    )

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
        corroboration_result=corroboration_res,
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
        corroboration_result=corroboration_res,
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
        actions.append("Confirm offer issuance independently before accepting; do not rely solely on an emailed link.")

    # 8. Confirmation Route (Task 12)
    confirmation_route: Optional[ConfirmationRoute] = corroboration_res.confirmation_route

    # Task 12 distinctions for Recommended Actions:
    # 1. Job vacancy corroboration
    has_role_supported = any(a.status == ClaimStatus.SUPPORTED and next((c.kind for c in claims if c.claim_id == a.claim_id), None) in (ClaimKind.ROLE, ClaimKind.JOB_REFERENCE) for a in assessed_claims)
    has_role_unresolved = any(a.status == ClaimStatus.UNRESOLVED and next((c.kind for c in claims if c.claim_id == a.claim_id), None) == ClaimKind.ROLE for a in assessed_claims)
    if has_role_supported:
        actions.append("Matching public vacancy records were found, but a public listing does not authenticate individual offer issuance; confirm directly with the employer.")
    elif has_role_unresolved:
        actions.append("No matching public vacancy record was corroborated; verify role opening directly through official employer channels.")

    # 2. Confirmation route
    if confirmation_route:
        actions.append(f"Use the independently verified {confirmation_route.channel.replace('_', ' ')} ({confirmation_route.destination}) to confirm whether this offer was formally issued.")
    else:
        actions.append("No independently sourced offer-confirmation channel was identified; contact the employer via official published directory or registry contacts.")

    # 3. Budget / provider limitation
    if any(e.code in ("INVESTIGATION_BUDGET_EXCEEDED", "INVESTIGATION_DEADLINE_EXCEEDED") for e in errors) or provider_outage:
        actions.append("Investigation search budget or deadline limits were reached before all checks completed; independently confirm remaining details.")

    # Deduplicate actions preserving order
    deduped_actions: List[str] = []
    seen_act = set()
    for a in actions:
        if a not in seen_act:
            seen_act.add(a)
            deduped_actions.append(a)

    # 9. Tool Trace
    tool_trace = recording_client.tool_calls

    # 10. Coverage
    distinct_failed_checks = len(recording_client.failed_searches) + sum(
        e.code in ("COMPANY_INVESTIGATION_ERROR", "AGENT_CHECK_FAILURE") for e in errors)
    # Claim execution counts are independent of whether a result resolved it.
    checked_claim_ids = set()
    claim_agents = {ClaimKind.EMPLOYER: "CompanyAgent", ClaimKind.SENDER_EMAIL: "RecruiterAgent",
                    ClaimKind.CONTACT_PHONE: "RecruiterAgent", ClaimKind.RECRUITER_NAME: "RecruiterAgent",
                    ClaimKind.COMPENSATION: "SalaryAgent", ClaimKind.PAYMENT_REQUEST: "ScamAgent",
                    ClaimKind.CREDENTIAL_REQUEST: "ScamAgent"}
    for claim in claims:
        if not claim.value or is_redaction_placeholder(claim.value) or claim.extraction_status == ExtractionStatus.UNCERTAIN:
            continue
        if claim.kind in (ClaimKind.ROLE, ClaimKind.LOCATION, ClaimKind.JOB_REFERENCE, ClaimKind.APPLICATION_URL):
            ass = next((a for a in assessed_claims if a.claim_id == claim.claim_id), None)
            if ass and ass.status != ClaimStatus.NOT_CHECKED:
                checked_claim_ids.add(claim.claim_id)
            continue
        finding = findings_map.get(claim_agents.get(claim.kind))
        if not finding:
            continue
        checked = finding.details.get("provider_status") == "SUCCESS"
        if claim.kind in (ClaimKind.PAYMENT_REQUEST, ClaimKind.CREDENTIAL_REQUEST):
            checked = bool(finding.details.get("local_scan_completed"))
        elif claim.kind == ClaimKind.CONTACT_PHONE:
            checked = (finding.details.get("checks", {}).get("phone_reports", {}).get("provider_status") == "SUCCESS")
        elif claim.kind == ClaimKind.RECRUITER_NAME:
            checked = any(a.claim_id == claim.claim_id and a.status.value == "SUPPORTED" for a in assessed_claims)
            checked = checked or any(c.status == EventStatus.COMPLETED and c.query and claim.value.lower() in c.query.lower()
                                     for c in recording_client.tool_calls)
        elif claim.kind == ClaimKind.SENDER_EMAIL and finding.details.get("provider_status") == "PARTIAL":
            checked = finding.details.get("checks", {}).get("email_reports", {}).get("provider_status") == "SUCCESS"
        if checked:
            checked_claim_ids.add(claim.claim_id)
    coverage = compute_coverage(
        claims=claims,
        assessed_claims=assessed_claims,
        failed_check_count=distinct_failed_checks,
        checked_claim_ids=checked_claim_ids,
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
