import re
import urllib.parse
from typing import List, Dict, Any, Optional, Set, Tuple

from app.schemas.analysis import AgentFinding, EvidenceItem, RiskLevel
from app.services.risk.assessment_models import (
    OverallOutcome,
    AuthenticityStatus,
    WarningSeverity,
    WarningBand,
    ExecutionStatus,
    ResolutionStatus,
    WarningSignal,
    CheckCoverageItem,
    CoverageSummary,
    StructuredAssessment,
)
from app.core.logging import logger


def canonicalize_url(url: Optional[str]) -> str:
    """
    Normalizes a URL to prevent duplicate counting while preserving meaning.
    Treats local document URIs as distinct document evidence, not public web sources.
    """
    if not url:
        return ""
    clean = url.strip()
    if clean.startswith("document://"):
        return clean.lower()

    try:
        parsed = urllib.parse.urlsplit(clean)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip("/")
        # Omit tracking query params
        return urllib.parse.urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))
    except Exception:
        return clean.lower()


class AssessmentEngine:
    """
    Unified assessment policy for AsliOffer (Task 8).
    Answers three distinct questions:
      1. Warning strength: What supported warning signals were found?
      2. Investigation coverage: Which checks ran, which were unavailable, and what remains unresolved?
      3. Offer authenticity: Always UNCONFIRMED for current pipeline (public web checks cannot
         authenticate individual employment offers without authorized employer confirmation).
    """

    ASSESSMENT_VERSION = "1.0.0"
    ASSESSMENT_METHOD = "structured_policy_v1"

    # Precise codes for strong adverse signals
    STRONG_ADVERSE_CODES = {
        "ADVANCE_FEE_DETECTED",
        "UPFRONT_FEE_DEMAND",
        "UNLOCK_PAYMENT_DETECTED",
        "UNLOCK_PAYMENT_DEMAND",
        "CREDENTIAL_THEFT_DETECTED",
        "CREDENTIAL_THEFT_DEMAND",
        "ADVERSE_PHONE_REPORT",
        "ADVERSE_EMAIL_REPORT",
    }

    # Precise codes for review-only concerns
    REVIEW_CONCERN_CODES = {
        "FREE_WEBMAIL_DOMAIN",
        "PERSONAL_EMAIL_DOMAIN",
        "RECRUITER_DOMAIN_MISMATCH",
        "AGENCY_MANDATE_UNCONFIRMED",
        "AGENCY_AFFILIATION_UNCONFIRMED",
        "SALARY_OUTLIER",
        "CANDIDATE_PAYMENT_DETECTED",
        "TELEGRAM_UNVERIFIED_CHANNEL",
        "SUSPICIOUS_PAYMENT_CHANNEL_OR_TERMS",
    }

    def assess(self, findings: List[AgentFinding]) -> StructuredAssessment:
        """
        Executes the unified assessment policy over agent findings.
        Guarantees deterministic, order-invariant evaluation without score inflation.
        """
        logger.info("AssessmentEngine evaluating %d findings", len(findings))

        # 1. Deduplicate Evidence and track sources
        unique_evidence, unique_urls = self._deduplicate_evidence(findings)

        # 2. Extract Check Coverage Items
        checks = self._extract_checks(findings)

        # 3. Extract Supported Warning Signals vs. Review Concerns vs. Gaps
        strong_signals, review_concerns, unresolved_issues = self._extract_signals_and_gaps(findings, checks)

        # 4. Determine Overall Outcome following strict precedence
        overall_outcome, policy_explanation = self._determine_overall_outcome(
            checks=checks,
            strong_signals=strong_signals,
            review_concerns=review_concerns,
            unresolved_issues=unresolved_issues,
            findings_count=len(findings),
        )

        # 5. Compute Warning Strength and Warning Band
        warning_strength, warning_band = self._compute_warning_strength(
            overall_outcome=overall_outcome,
            strong_signals=strong_signals,
            review_concerns=review_concerns,
        )

        # 6. Compute Coverage Summary
        coverage_summary = self._compute_coverage_summary(checks, unresolved_issues)

        # Supporting evidence references (deduplicated URLs)
        supporting_evidence_refs = sorted(list(unique_urls))

        return StructuredAssessment(
            overall_outcome=overall_outcome,
            authenticity_status=AuthenticityStatus.UNCONFIRMED,
            warning_strength=warning_strength,
            warning_band=warning_band,
            supported_warning_signals=strong_signals,
            review_only_concerns=review_concerns,
            coverage_summary=coverage_summary,
            individual_checks=checks,
            supporting_evidence_refs=supporting_evidence_refs,
            unresolved_issues=unresolved_issues,
            assessment_method=self.ASSESSMENT_METHOD,
            assessment_version=self.ASSESSMENT_VERSION,
            policy_explanation=policy_explanation,
        )

    def _deduplicate_evidence(self, findings: List[AgentFinding]) -> Tuple[List[EvidenceItem], Set[str]]:
        seen_keys: Set[Tuple[str, str]] = set()
        unique_items: List[EvidenceItem] = []
        unique_urls: Set[str] = set()

        for f in findings:
            for ev in f.evidence:
                canon_url = canonicalize_url(ev.source_url)
                title_key = (ev.title or "").strip().lower()
                key = (canon_url, title_key)
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_items.append(ev)
                    if canon_url:
                        unique_urls.add(canon_url)

        return unique_items, unique_urls

    def _extract_checks(self, findings: List[AgentFinding]) -> List[CheckCoverageItem]:
        agent_map = {f.agent_name: f for f in findings}
        checks: List[CheckCoverageItem] = []

        # Check 1: LOCAL_DOCUMENT_SCAN (ScamAgent)
        checks.append(self._check_local_document_scan(agent_map.get("ScamAgent")))

        # Check 2: EXTERNAL_SCAM_REPORTS (ScamAgent)
        checks.append(self._check_external_scam_reports(agent_map.get("ScamAgent")))

        # Check 3: COMPANY_IDENTITY_CHECK (CompanyAgent)
        checks.append(self._check_company_identity(agent_map.get("CompanyAgent")))

        # Check 4: RECRUITER_CONTACT_REPUTATION (RecruiterAgent)
        checks.append(self._check_recruiter_contact_reputation(agent_map.get("RecruiterAgent")))

        # Check 5: RECRUITER_AFFILIATION_CHECK (RecruiterAgent)
        checks.append(self._check_recruiter_affiliation(agent_map.get("RecruiterAgent")))

        # Check 6: AGENCY_AUTHORIZATION_CHECK (RecruiterAgent)
        checks.append(self._check_agency_authorization(agent_map.get("RecruiterAgent")))

        # Check 7: COMPENSATION_BENCHMARK (SalaryAgent)
        checks.append(self._check_compensation_benchmark(agent_map.get("SalaryAgent")))

        return checks

    def _check_local_document_scan(self, finding: Optional[AgentFinding]) -> CheckCoverageItem:
        if not finding:
            return CheckCoverageItem(
                check_id="LOCAL_DOCUMENT_SCAN",
                check_name="Local Document Scam Pattern Scan",
                agent_name="ScamAgent",
                execution_status=ExecutionStatus.NOT_CHECKED,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                missing_input="Document text not evaluated by ScamAgent",
                remaining_uncertainty="Document has not been scanned for upfront fee or credential theft patterns",
            )

        details = finding.details or {}
        local_completed = details.get("local_scan_completed", True)
        active_signals = details.get("risk_signals", [])
        has_active_demands = bool(
            details.get("fee_detected")
            or details.get("unlock_earnings_detected")
            or details.get("otp_requested")
            or details.get("password_requested")
            or any(s in self.STRONG_ADVERSE_CODES for s in active_signals)
            or finding.verdict == "HIGH_RISK"
        )
        is_ambiguous = finding.verdict == "NEEDS_REVIEW"

        if local_completed:
            execution_status = ExecutionStatus.COMPLETED
            if has_active_demands:
                resolution_status = ResolutionStatus.SUPPORTED
                uncertainty = None
            elif is_ambiguous:
                resolution_status = ResolutionStatus.UNCONFIRMED
                uncertainty = "Ambiguous terms or unverified communications present in document text"
            else:
                resolution_status = ResolutionStatus.NO_MATCH
                uncertainty = None
        else:
            execution_status = ExecutionStatus.UNAVAILABLE
            resolution_status = ResolutionStatus.UNCONFIRMED
            uncertainty = "Local document pattern scan could not complete"

        evidence_refs = [
            canonicalize_url(e.source_url)
            for e in finding.evidence
            if e.source_url.startswith("document://")
        ]

        return CheckCoverageItem(
            check_id="LOCAL_DOCUMENT_SCAN",
            check_name="Local Document Scam Pattern Scan",
            agent_name="ScamAgent",
            execution_status=execution_status,
            resolution_status=resolution_status,
            applicability=True,
            evidence_refs=evidence_refs,
            remaining_uncertainty=uncertainty,
        )

    def _check_external_scam_reports(self, finding: Optional[AgentFinding]) -> CheckCoverageItem:
        if not finding:
            return CheckCoverageItem(
                check_id="EXTERNAL_SCAM_REPORTS",
                check_name="Public Complaint & Scam Search",
                agent_name="ScamAgent",
                execution_status=ExecutionStatus.NOT_CHECKED,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                missing_input="External scam search was not initiated",
                remaining_uncertainty="External search for employer/payment complaints did not run",
            )

        details = finding.details or {}
        checks_dict = details.get("checks", {})
        provider_status = details.get("provider_status", "SUCCESS")
        search_status = details.get("search_status", "SUCCESS")
        search_source = details.get("search_source")

        # Exclude DEMO results from public verification evidence
        if search_source == "DEMO" or any(c.get("search_source") == "DEMO" for c in checks_dict.values()):
            return CheckCoverageItem(
                check_id="EXTERNAL_SCAM_REPORTS",
                check_name="Public Complaint & Scam Search",
                agent_name="ScamAgent",
                execution_status=ExecutionStatus.UNAVAILABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                failure_reason="Search returned demo/mock results; not verified against live public records",
                remaining_uncertainty="Live public scam reports could not be independently queried",
            )

        is_failed = provider_status == "FAILED" or search_status == "PROVIDER_FAILURE"
        is_partial = provider_status == "PARTIAL" or search_status == "PARTIAL"

        public_evidence = [
            canonicalize_url(e.source_url)
            for e in finding.evidence
            if not e.source_url.startswith("document://")
        ]

        if is_failed:
            return CheckCoverageItem(
                check_id="EXTERNAL_SCAM_REPORTS",
                check_name="Public Complaint & Scam Search",
                agent_name="ScamAgent",
                execution_status=ExecutionStatus.UNAVAILABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                failure_reason=details.get("error") or "External search provider outage",
                remaining_uncertainty="External adverse complaint databases could not be queried",
            )

        if is_partial:
            # Partial checks retain successful and failed subchecks
            failed_sub = [name for name, c in checks_dict.items() if c.get("provider_status") == "FAILED"]
            failure_note = f"External subqueries failed: {', '.join(failed_sub)}" if failed_sub else "Partial query failure"
            return CheckCoverageItem(
                check_id="EXTERNAL_SCAM_REPORTS",
                check_name="Public Complaint & Scam Search",
                agent_name="ScamAgent",
                execution_status=ExecutionStatus.UNAVAILABLE,
                resolution_status=ResolutionStatus.SUPPORTED if public_evidence else ResolutionStatus.UNCONFIRMED,
                applicability=True,
                failure_reason=failure_note,
                evidence_refs=public_evidence,
                remaining_uncertainty="Some external scam queries succeeded but others were unavailable",
            )

        # Completed execution
        if public_evidence:
            if finding.verdict == "VERIFIED":
                resolution_status = ResolutionStatus.NO_MATCH
            else:
                resolution_status = ResolutionStatus.SUPPORTED
            uncertainty = None
        else:
            resolution_status = ResolutionStatus.NO_MATCH
            uncertainty = None

        return CheckCoverageItem(
            check_id="EXTERNAL_SCAM_REPORTS",
            check_name="Public Complaint & Scam Search",
            agent_name="ScamAgent",
            execution_status=ExecutionStatus.COMPLETED,
            resolution_status=resolution_status,
            applicability=True,
            evidence_refs=public_evidence,
            remaining_uncertainty=uncertainty,
        )

    def _check_company_identity(self, finding: Optional[AgentFinding]) -> CheckCoverageItem:
        if not finding:
            return CheckCoverageItem(
                check_id="COMPANY_IDENTITY_CHECK",
                check_name="Employer Identity & Web Presence Check",
                agent_name="CompanyAgent",
                execution_status=ExecutionStatus.NOT_CHECKED,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                missing_input="Company name was not provided or CompanyAgent did not run",
                remaining_uncertainty="Employer identity and domain could not be verified",
            )

        details = finding.details or {}
        provider_status = details.get("provider_status", "SUCCESS")
        search_status = details.get("search_status")
        search_source = details.get("search_source")
        evidence_urls = [canonicalize_url(e.source_url) for e in finding.evidence]

        # Demo exclusion
        if search_source == "DEMO":
            return CheckCoverageItem(
                check_id="COMPANY_IDENTITY_CHECK",
                check_name="Employer Identity & Web Presence Check",
                agent_name="CompanyAgent",
                execution_status=ExecutionStatus.UNAVAILABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                failure_reason="Search returned demo/mock results; not verified against public records",
                remaining_uncertainty="Company identity not verified against live web data",
            )

        if provider_status == "FAILED" or search_status in ("PROVIDER_FAILURE", "TIMEOUT", "AUTH_FAILURE"):
            return CheckCoverageItem(
                check_id="COMPANY_IDENTITY_CHECK",
                check_name="Employer Identity & Web Presence Check",
                agent_name="CompanyAgent",
                execution_status=ExecutionStatus.UNAVAILABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                failure_reason=details.get("error") or "Company search provider unavailable",
                remaining_uncertainty="External search for company registration/domain could not execute",
            )

        # Successful search with zero results
        if search_status in ("ZERO_RESULTS", "SUCCESSFUL_EMPTY") or (not finding.evidence and finding.verdict in ("UNVERIFIED", "CANNOT_VERIFY")):
            return CheckCoverageItem(
                check_id="COMPANY_IDENTITY_CHECK",
                check_name="Employer Identity & Web Presence Check",
                agent_name="CompanyAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.NO_MATCH,
                applicability=True,
                remaining_uncertainty="No matching public web presence found for claimed employer name",
            )

        if finding.verdict == "VERIFIED":
            return CheckCoverageItem(
                check_id="COMPANY_IDENTITY_CHECK",
                check_name="Employer Identity & Web Presence Check",
                agent_name="CompanyAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.SUPPORTED,
                applicability=True,
                evidence_refs=evidence_urls,
            )

        return CheckCoverageItem(
            check_id="COMPANY_IDENTITY_CHECK",
            check_name="Employer Identity & Web Presence Check",
            agent_name="CompanyAgent",
            execution_status=ExecutionStatus.COMPLETED,
            resolution_status=ResolutionStatus.UNCONFIRMED,
            applicability=True,
            evidence_refs=evidence_urls,
            remaining_uncertainty=finding.summary or "Company web presence unconfirmed",
        )

    def _check_recruiter_contact_reputation(self, finding: Optional[AgentFinding]) -> CheckCoverageItem:
        if not finding:
            return CheckCoverageItem(
                check_id="RECRUITER_CONTACT_REPUTATION",
                check_name="Recruiter Contact Adverse Reports Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.NOT_CHECKED,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                missing_input="No recruiter contact evaluated",
                remaining_uncertainty="Sender phone and email have not been checked against adverse reports",
            )

        details = finding.details or {}
        reason_code = details.get("reason_code")
        if reason_code in ("NO_CONTACT_PROVIDED", "INVALID_CONTACT_INPUT"):
            return CheckCoverageItem(
                check_id="RECRUITER_CONTACT_REPUTATION",
                check_name="Recruiter Contact Adverse Reports Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.NOT_CHECKED,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                missing_input="No valid recruiter contact provided in offer",
                remaining_uncertainty="Lack of sender contact prevents adverse contact reputation verification",
            )

        dims = details.get("assessment_dimensions", {})
        adv_dim = dims.get("adverse_reports", {}) or details.get("adverse_reports", {})
        adv_status = adv_dim.get("status")
        phone_flagged = bool(details.get("phone_flagged") or adv_dim.get("phone_flagged"))
        email_flagged = bool(details.get("email_flagged") or adv_dim.get("email_flagged"))
        provider_status = details.get("provider_status", "SUCCESS")

        evidence_urls = [canonicalize_url(e.source_url) for e in finding.evidence]

        if adv_status == "CHECK_UNAVAILABLE" or (provider_status == "FAILED" and not (phone_flagged or email_flagged)):
            return CheckCoverageItem(
                check_id="RECRUITER_CONTACT_REPUTATION",
                check_name="Recruiter Contact Adverse Reports Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.UNAVAILABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                failure_reason=details.get("error") or "Contact reputation search unavailable",
                remaining_uncertainty="Adverse contact database search failed or timed out",
            )

        if phone_flagged or email_flagged or reason_code in ("ADVERSE_PHONE_REPORT", "ADVERSE_EMAIL_REPORT"):
            return CheckCoverageItem(
                check_id="RECRUITER_CONTACT_REPUTATION",
                check_name="Recruiter Contact Adverse Reports Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.SUPPORTED,
                applicability=True,
                evidence_refs=evidence_urls,
            )

        return CheckCoverageItem(
            check_id="RECRUITER_CONTACT_REPUTATION",
            check_name="Recruiter Contact Adverse Reports Check",
            agent_name="RecruiterAgent",
            execution_status=ExecutionStatus.COMPLETED,
            resolution_status=ResolutionStatus.NO_MATCH,
            applicability=True,
            evidence_refs=evidence_urls,
        )

    def _check_recruiter_affiliation(self, finding: Optional[AgentFinding]) -> CheckCoverageItem:
        if not finding:
            return CheckCoverageItem(
                check_id="RECRUITER_AFFILIATION_CHECK",
                check_name="Recruiter Domain Alignment & Employer Affiliation Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.NOT_CHECKED,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                missing_input="No recruiter contact evaluated",
                remaining_uncertainty="Recruiter affiliation and email domain have not been investigated",
            )

        details = finding.details or {}
        reason_code = details.get("reason_code")
        if reason_code in ("NO_CONTACT_PROVIDED", "INVALID_CONTACT_INPUT"):
            return CheckCoverageItem(
                check_id="RECRUITER_AFFILIATION_CHECK",
                check_name="Recruiter Domain Alignment & Employer Affiliation Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.NOT_CHECKED,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                missing_input="No valid recruiter email provided",
                remaining_uncertainty="Lack of sender email prevents domain alignment check",
            )

        dims = details.get("assessment_dimensions", {})
        dom_dim = dims.get("domain_alignment", {})
        is_free_email = bool(details.get("is_free_email") or dom_dim.get("is_free_email"))
        domain_match = details.get("domain_match") if "domain_match" in details else dom_dim.get("domain_match")
        affiliation_status = details.get("recruiter_affiliation_status")
        affiliation_strength = details.get("recruiter_affiliation_strength")
        provider_status = details.get("provider_status", "SUCCESS")

        evidence_urls = [canonicalize_url(e.source_url) for e in finding.evidence]

        if provider_status == "FAILED" and domain_match is None and not is_free_email:
            return CheckCoverageItem(
                check_id="RECRUITER_AFFILIATION_CHECK",
                check_name="Recruiter Domain Alignment & Employer Affiliation Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.UNAVAILABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                failure_reason=details.get("error") or "Recruiter search unavailable",
                remaining_uncertainty="Search provider unavailable for recruiter domain alignment",
            )

        if is_free_email:
            return CheckCoverageItem(
                check_id="RECRUITER_AFFILIATION_CHECK",
                check_name="Recruiter Domain Alignment & Employer Affiliation Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.CONFLICTING,
                applicability=True,
                evidence_refs=evidence_urls,
                remaining_uncertainty="Recruiter contact uses personal webmail domain for corporate hiring",
            )

        if domain_match is False:
            return CheckCoverageItem(
                check_id="RECRUITER_AFFILIATION_CHECK",
                check_name="Recruiter Domain Alignment & Employer Affiliation Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.CONFLICTING,
                applicability=True,
                evidence_refs=evidence_urls,
                remaining_uncertainty="Recruiter email domain does not match employer's official domain",
            )

        if (
            (affiliation_status == "SUPPORTED" and affiliation_strength == "strong_employer_published")
            or details.get("reason_code") == "RECRUITER_AFFILIATION_VERIFIED"
            or (finding.verdict == "VERIFIED" and len(evidence_urls) > 0)
        ):
            return CheckCoverageItem(
                check_id="RECRUITER_AFFILIATION_CHECK",
                check_name="Recruiter Domain Alignment & Employer Affiliation Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.SUPPORTED,
                applicability=True,
                evidence_refs=evidence_urls,
            )

        return CheckCoverageItem(
            check_id="RECRUITER_AFFILIATION_CHECK",
            check_name="Recruiter Domain Alignment & Employer Affiliation Check",
            agent_name="RecruiterAgent",
            execution_status=ExecutionStatus.COMPLETED,
            resolution_status=ResolutionStatus.UNCONFIRMED,
            applicability=True,
            evidence_refs=evidence_urls,
            remaining_uncertainty="Domain matched employer, but individual recruiter affiliation remains unconfirmed",
        )

    def _check_agency_authorization(self, finding: Optional[AgentFinding]) -> CheckCoverageItem:
        if not finding:
            return CheckCoverageItem(
                check_id="AGENCY_AUTHORIZATION_CHECK",
                check_name="Staffing Agency Representation Mandate Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.NOT_APPLICABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=False,
            )

        details = finding.details or {}
        is_agency = bool(details.get("is_agency"))
        if not is_agency:
            return CheckCoverageItem(
                check_id="AGENCY_AUTHORIZATION_CHECK",
                check_name="Staffing Agency Representation Mandate Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.NOT_APPLICABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=False,
            )

        agency_status = details.get("agency_authorization_status")
        evidence_urls = [canonicalize_url(e.source_url) for e in finding.evidence]

        if agency_status == "SUPPORTED":
            return CheckCoverageItem(
                check_id="AGENCY_AUTHORIZATION_CHECK",
                check_name="Staffing Agency Representation Mandate Check",
                agent_name="RecruiterAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.SUPPORTED,
                applicability=True,
                evidence_refs=evidence_urls,
            )

        return CheckCoverageItem(
            check_id="AGENCY_AUTHORIZATION_CHECK",
            check_name="Staffing Agency Representation Mandate Check",
            agent_name="RecruiterAgent",
            execution_status=ExecutionStatus.COMPLETED,
            resolution_status=ResolutionStatus.UNCONFIRMED,
            applicability=True,
            evidence_refs=evidence_urls,
            remaining_uncertainty="Agency footprint recognized, but client representation mandate requires secondary confirmation",
        )

    def _check_compensation_benchmark(self, finding: Optional[AgentFinding]) -> CheckCoverageItem:
        if not finding:
            return CheckCoverageItem(
                check_id="COMPENSATION_BENCHMARK",
                check_name="Market Compensation Plausibility Benchmark",
                agent_name="SalaryAgent",
                execution_status=ExecutionStatus.NOT_APPLICABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=False,
                missing_input="No compensation figure provided in offer",
            )

        details = finding.details or {}
        offered_salary = details.get("offered_salary")
        interpreted_as = details.get("interpreted_as")
        provider_status = details.get("provider_status", "SUCCESS")
        evidence_urls = [canonicalize_url(e.source_url) for e in finding.evidence]

        # Inapplicable if no salary or monthly stipend (cannot be checked against annual bands)
        if not offered_salary or offered_salary in ("Undisclosed", ""):
            return CheckCoverageItem(
                check_id="COMPENSATION_BENCHMARK",
                check_name="Market Compensation Plausibility Benchmark",
                agent_name="SalaryAgent",
                execution_status=ExecutionStatus.NOT_APPLICABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=False,
                missing_input="No usable compensation figure stated in offer",
            )

        if interpreted_as == "monthly stipend":
            return CheckCoverageItem(
                check_id="COMPENSATION_BENCHMARK",
                check_name="Market Compensation Plausibility Benchmark",
                agent_name="SalaryAgent",
                execution_status=ExecutionStatus.NOT_APPLICABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=False,
                remaining_uncertainty="Monthly stipend cannot be benchmarked against annual market compensation bands",
            )

        if provider_status == "FAILED":
            return CheckCoverageItem(
                check_id="COMPENSATION_BENCHMARK",
                check_name="Market Compensation Plausibility Benchmark",
                agent_name="SalaryAgent",
                execution_status=ExecutionStatus.UNAVAILABLE,
                resolution_status=ResolutionStatus.UNCONFIRMED,
                applicability=True,
                failure_reason=details.get("error") or "Salary search provider unavailable",
                remaining_uncertainty="External salary baseline could not be retrieved",
            )

        is_anomaly = bool(details.get("anomaly") or finding.verdict == "NEEDS_REVIEW")
        if is_anomaly:
            return CheckCoverageItem(
                check_id="COMPENSATION_BENCHMARK",
                check_name="Market Compensation Plausibility Benchmark",
                agent_name="SalaryAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.CONFLICTING,
                applicability=True,
                evidence_refs=evidence_urls,
                remaining_uncertainty="Stated compensation is unusually high for role and may be used as bait",
            )

        if finding.verdict == "VERIFIED":
            return CheckCoverageItem(
                check_id="COMPENSATION_BENCHMARK",
                check_name="Market Compensation Plausibility Benchmark",
                agent_name="SalaryAgent",
                execution_status=ExecutionStatus.COMPLETED,
                resolution_status=ResolutionStatus.SUPPORTED,
                applicability=True,
                evidence_refs=evidence_urls,
            )

        return CheckCoverageItem(
            check_id="COMPENSATION_BENCHMARK",
            check_name="Market Compensation Plausibility Benchmark",
            agent_name="SalaryAgent",
            execution_status=ExecutionStatus.COMPLETED,
            resolution_status=ResolutionStatus.NO_MATCH,
            applicability=True,
            remaining_uncertainty="No external salary benchmark match established",
        )

    def _extract_signals_and_gaps(
        self,
        findings: List[AgentFinding],
        checks: List[CheckCoverageItem],
    ) -> Tuple[List[WarningSignal], List[WarningSignal], List[str]]:
        agent_map = {f.agent_name: f for f in findings}
        strong_signals: List[WarningSignal] = []
        review_concerns: List[WarningSignal] = []
        unresolved_issues: List[str] = []

        seen_strong_codes: Set[str] = set()
        seen_review_codes: Set[str] = set()

        # --- A. ScamAgent Signals ---
        scam = agent_map.get("ScamAgent")
        if scam:
            s_details = scam.details or {}
            risk_signals = s_details.get("risk_signals", [])
            s_evidence = [canonicalize_url(e.source_url) for e in scam.evidence]

            # Credential theft
            if (
                "CREDENTIAL_THEFT_DEMAND" in risk_signals
                or s_details.get("otp_requested")
                or s_details.get("password_requested")
                or s_details.get("reason_code") == "CREDENTIAL_THEFT_DETECTED"
            ):
                code = "CREDENTIAL_THEFT_DETECTED"
                if code not in seen_strong_codes:
                    seen_strong_codes.add(code)
                    strong_signals.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.STRONG_ADVERSE,
                            title="Account Passwords or Bank OTP Solicited",
                            description="The submitted document solicits bank OTPs, account passwords, or access credentials.",
                            source_agent="ScamAgent",
                            evidence_refs=s_evidence,
                        )
                    )

            # Unlock payment demand
            if (
                "UNLOCK_PAYMENT_DEMAND" in risk_signals
                or s_details.get("unlock_earnings_detected")
                or s_details.get("reason_code") == "UNLOCK_PAYMENT_DETECTED"
            ):
                code = "UNLOCK_PAYMENT_DETECTED"
                if code not in seen_strong_codes:
                    seen_strong_codes.add(code)
                    strong_signals.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.STRONG_ADVERSE,
                            title="Payment to Unlock Earnings Demanded",
                            description="Payment or deposit required to release earned wages or unlock job tasks.",
                            source_agent="ScamAgent",
                            evidence_refs=s_evidence,
                        )
                    )

            # Advance fee demand
            if (
                "UPFRONT_FEE_DEMAND" in risk_signals
                or (s_details.get("fee_detected") and not s_details.get("unlock_earnings_detected"))
                or s_details.get("reason_code") == "ADVANCE_FEE_DETECTED"
            ):
                code = "ADVANCE_FEE_DETECTED"
                if code not in seen_strong_codes:
                    seen_strong_codes.add(code)
                    strong_signals.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.STRONG_ADVERSE,
                            title="Mandatory Upfront Fee or Security Deposit Demanded",
                            description="The submitted document demands an upfront recruitment fee, training charge, or laptop deposit.",
                            source_agent="ScamAgent",
                            evidence_refs=s_evidence,
                        )
                    )

            # Direct UPI request (review concern if no fee, strong if combined with fee)
            if "UPI_PAYMENT_REQUEST" in risk_signals or s_details.get("reason_code") == "CANDIDATE_PAYMENT_DETECTED":
                if not any(s.code == "ADVANCE_FEE_DETECTED" for s in strong_signals):
                    code = "CANDIDATE_PAYMENT_DETECTED"
                    if code not in seen_review_codes:
                        seen_review_codes.add(code)
                        review_concerns.append(
                            WarningSignal(
                                code=code,
                                severity=WarningSeverity.REVIEW_CONCERN,
                                title="Candidate Payment Requested via UPI / Mobile Wallet",
                                description="Candidate directed to remit payment via UPI or mobile wallet without confirmed fee demand.",
                                source_agent="ScamAgent",
                                evidence_refs=s_evidence,
                            )
                        )

            # Telegram unverified channel
            if s_details.get("reason_code") == "TELEGRAM_UNVERIFIED_CHANNEL" or (
                s_details.get("telegram_present") and scam.verdict == "NEEDS_REVIEW"
            ):
                code = "TELEGRAM_UNVERIFIED_CHANNEL"
                if code not in seen_review_codes:
                    seen_review_codes.add(code)
                    review_concerns.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.REVIEW_CONCERN,
                            title="Telegram Communication Channel Used",
                            description="Recruitment conducted via informal Telegram messaging without verifiable corporate presence.",
                            source_agent="ScamAgent",
                            evidence_refs=s_evidence,
                        )
                    )

            # Generic ScamAgent fallback for older findings
            if scam.verdict == "HIGH_RISK":
                s_sum = (scam.summary or "").lower()
                if any(w in s_sum for w in ("fee", "deposit", "charge", "upfront")):
                    code = "ADVANCE_FEE_DETECTED"
                    title = "Mandatory Upfront Fee or Security Deposit Demanded"
                elif any(w in s_sum for w in ("otp", "password", "credential")):
                    code = "CREDENTIAL_THEFT_DETECTED"
                    title = "Account Passwords or Bank OTP Solicited"
                elif "unlock" in s_sum:
                    code = "UNLOCK_PAYMENT_DETECTED"
                    title = "Payment to Unlock Earnings Demanded"
                else:
                    code = s_details.get("reason_code") or "SCAM_SIGNAL_DETECTED"
                    title = "Critical Scam Markers Detected"
                if code not in seen_strong_codes:
                    seen_strong_codes.add(code)
                    strong_signals.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.STRONG_ADVERSE,
                            title=title,
                            description=scam.summary,
                            source_agent="ScamAgent",
                            evidence_refs=s_evidence,
                        )
                    )
            elif scam.verdict == "NEEDS_REVIEW" and not review_concerns:
                code = s_details.get("reason_code") or "SUSPICIOUS_PAYMENT_CHANNEL_OR_TERMS"
                if code not in seen_review_codes:
                    seen_review_codes.add(code)
                    review_concerns.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.REVIEW_CONCERN,
                            title="Scam Assessment Requires Review",
                            description=scam.summary,
                            source_agent="ScamAgent",
                            evidence_refs=s_evidence,
                        )
                    )

        # --- B. RecruiterAgent Signals ---
        rec = agent_map.get("RecruiterAgent")
        if rec:
            r_details = rec.details or {}
            r_evidence = [canonicalize_url(e.source_url) for e in rec.evidence]
            r_reason = r_details.get("reason_code")

            # Adverse contact reports (Strong adverse)
            if r_details.get("phone_flagged") or r_reason == "ADVERSE_PHONE_REPORT":
                code = "ADVERSE_PHONE_REPORT"
                if code not in seen_strong_codes:
                    seen_strong_codes.add(code)
                    strong_signals.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.STRONG_ADVERSE,
                            title="Recruiter Phone Reported in Public Scam Database",
                            description="Recruiter phone number appears in public complaint or cybercrime scam reports.",
                            source_agent="RecruiterAgent",
                            evidence_refs=r_evidence,
                        )
                    )

            if r_details.get("email_flagged") or r_reason == "ADVERSE_EMAIL_REPORT":
                code = "ADVERSE_EMAIL_REPORT"
                if code not in seen_strong_codes:
                    seen_strong_codes.add(code)
                    strong_signals.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.STRONG_ADVERSE,
                            title="Recruiter Email Reported in Public Scam Database",
                            description="Recruiter email address appears in public complaint or cybercrime scam reports.",
                            source_agent="RecruiterAgent",
                            evidence_refs=r_evidence,
                        )
                    )

            r_sum = (rec.summary or "").lower()
            if (
                r_details.get("is_free_email")
                or r_reason in ("FREE_WEBMAIL_DOMAIN", "PERSONAL_EMAIL_DOMAIN")
                or any(w in r_sum for w in ("webmail", "gmail", "yahoo", "personal email"))
            ):
                code = "PERSONAL_EMAIL_DOMAIN"
                if code not in seen_review_codes:
                    seen_review_codes.add(code)
                    review_concerns.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.REVIEW_CONCERN,
                            title="Personal Webmail Used for Corporate Role",
                            description="Recruiter uses a free webmail domain (e.g. Gmail/Yahoo) rather than an official corporate email address.",
                            source_agent="RecruiterAgent",
                            evidence_refs=r_evidence,
                        )
                    )

            # Domain mismatch (Review concern)
            if r_details.get("domain_match") is False or r_reason == "RECRUITER_DOMAIN_MISMATCH":
                code = "RECRUITER_DOMAIN_MISMATCH"
                if code not in seen_review_codes:
                    seen_review_codes.add(code)
                    review_concerns.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.REVIEW_CONCERN,
                            title="Sender Domain Does Not Match Employer Domain",
                            description="Sender's email domain does not match the official domain of the hiring company.",
                            source_agent="RecruiterAgent",
                            evidence_refs=r_evidence,
                        )
                    )

            # Agency mandate unconfirmed (Review concern)
            if r_reason == "AGENCY_MANDATE_UNCONFIRMED":
                code = "AGENCY_MANDATE_UNCONFIRMED"
                if code not in seen_review_codes:
                    seen_review_codes.add(code)
                    review_concerns.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.REVIEW_CONCERN,
                            title="Staffing Agency Client Mandate Unconfirmed",
                            description="Recruiter operates under third-party staffing agency; client representation mandate requires confirmation.",
                            source_agent="RecruiterAgent",
                            evidence_refs=r_evidence,
                        )
                    )

            if r_reason == "AGENCY_AFFILIATION_UNCONFIRMED":
                code = "AGENCY_AFFILIATION_UNCONFIRMED"
                if code not in seen_review_codes:
                    seen_review_codes.add(code)
                    review_concerns.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.REVIEW_CONCERN,
                            title="Recruiter Agency Affiliation Unconfirmed",
                            description="Agency existence recognized, but recruiter affiliation with agency remains unconfirmed.",
                            source_agent="RecruiterAgent",
                            evidence_refs=r_evidence,
                        )
                    )

        # --- C. SalaryAgent Signals ---
        sal = agent_map.get("SalaryAgent")
        if sal:
            sal_details = sal.details or {}
            sal_evidence = [canonicalize_url(e.source_url) for e in sal.evidence]
            if sal_details.get("anomaly") is True or sal.verdict == "NEEDS_REVIEW":
                code = "SALARY_OUTLIER"
                if code not in seen_review_codes:
                    seen_review_codes.add(code)
                    review_concerns.append(
                        WarningSignal(
                            code=code,
                            severity=WarningSeverity.REVIEW_CONCERN,
                            title="Stated Compensation Significantly Exceeds Market Bands",
                            description="Offered pay is unusually high for role and may be used as bait.",
                            source_agent="SalaryAgent",
                            evidence_refs=sal_evidence,
                        )
                    )

        # --- D. Gaps and Remaining Uncertainties (Missing Evidence / Provider Failures) ---
        for ch in checks:
            if ch.applicability:
                if ch.execution_status == ExecutionStatus.UNAVAILABLE:
                    unresolved_issues.append(
                        f"External check '{ch.check_name}' unavailable: {ch.failure_reason or 'provider outage'}."
                    )
                elif ch.execution_status == ExecutionStatus.NOT_CHECKED:
                    unresolved_issues.append(
                        f"Check '{ch.check_name}' was not run: {ch.missing_input or 'missing input'}."
                    )
                elif ch.resolution_status in (ResolutionStatus.NO_MATCH, ResolutionStatus.UNCONFIRMED, ResolutionStatus.CONFLICTING):
                    if ch.remaining_uncertainty:
                        unresolved_issues.append(ch.remaining_uncertainty)

        return strong_signals, review_concerns, unresolved_issues

    def _determine_overall_outcome(
        self,
        checks: List[CheckCoverageItem],
        strong_signals: List[WarningSignal],
        review_concerns: List[WarningSignal],
        unresolved_issues: List[str],
        findings_count: int,
    ) -> Tuple[OverallOutcome, str]:
        """
        Enforces strict outcome precedence:
          1. Supported strong adverse signal -> HIGH_RISK
          2. Supported review concern -> NEEDS_REVIEW
          3. No strong/review signal but material coverage/resolution gaps -> CANNOT_VERIFY
          4. No strong/review signal and sufficient applicable checks -> NO_STRONG_RISK_SIGNALS
        """
        # Precedence 1: Supported strong adverse signals
        if strong_signals:
            titles = [s.title for s in strong_signals]
            explanation = (
                f"HIGH_RISK: Supported strong adverse warning signals detected ({'; '.join(titles)}). "
                "Offer exhibits severe scam or credential theft characteristics."
            )
            return OverallOutcome.HIGH_RISK, explanation

        # Precedence 2: Supported review-only concerns
        if review_concerns:
            titles = [c.title for c in review_concerns]
            explanation = (
                f"NEEDS_REVIEW: Offer contains contextual concerns requiring manual verification ({'; '.join(titles)}). "
                "No definitive proof of fraud was established, but credentials require secondary confirmation."
            )
            return OverallOutcome.NEEDS_REVIEW, explanation

        # If findings list is empty or checks were not run
        if findings_count == 0:
            return (
                OverallOutcome.CANNOT_VERIFY,
                "CANNOT_VERIFY: No agent findings were provided to evaluate this offer.",
            )

        # Precedence 3 & 4: Check for material coverage / resolution gaps
        material_gaps: List[str] = []

        check_dict = {c.check_id: c for c in checks}

        # Essential check 1: Local Document Scan must be completed
        local_scan = check_dict.get("LOCAL_DOCUMENT_SCAN")
        if not local_scan or local_scan.execution_status != ExecutionStatus.COMPLETED:
            material_gaps.append("Local document scan incomplete")

        # Essential check 2: Company Identity Check must be completed and supported
        comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
        if not comp_check or comp_check.execution_status != ExecutionStatus.COMPLETED:
            material_gaps.append("Employer corporate web footprint could not be verified")
        elif comp_check.resolution_status != ResolutionStatus.SUPPORTED:
            material_gaps.append("No established corporate footprint found for employer")

        # Essential check 3: External Scam Search must be completed
        scam_check = check_dict.get("EXTERNAL_SCAM_REPORTS")
        if not scam_check or scam_check.execution_status != ExecutionStatus.COMPLETED:
            material_gaps.append("External public scam search was unavailable")

        # Essential check 4: Recruiter Contact Check must not have failed or been unprovided
        rec_rep = check_dict.get("RECRUITER_CONTACT_REPUTATION")
        if rec_rep and rec_rep.execution_status == ExecutionStatus.UNAVAILABLE:
            material_gaps.append("Recruiter adverse contact search was unavailable")
        elif rec_rep and rec_rep.execution_status == ExecutionStatus.NOT_CHECKED:
            material_gaps.append("No valid recruiter contact provided for independent verification")

        rec_aff = check_dict.get("RECRUITER_AFFILIATION_CHECK")
        if rec_aff and rec_aff.execution_status == ExecutionStatus.UNAVAILABLE:
            material_gaps.append("Recruiter affiliation check was unavailable")
        elif rec_aff and rec_aff.resolution_status != ResolutionStatus.SUPPORTED:
            material_gaps.append("Recruiter identity/affiliation could not be confirmed")

        if material_gaps:
            explanation = (
                f"CANNOT_VERIFY: Public evidence is inconclusive ({'; '.join(material_gaps)}). "
                "Missing evidence or provider outages do not establish fraud, but prevent positive verification."
            )
            return OverallOutcome.CANNOT_VERIFY, explanation

        # Sufficient applicable checks completed cleanly!
        explanation = (
            "NO_STRONG_RISK_SIGNALS: Completed investigation found no supported adverse signals or review concerns. "
            "Note: Authenticity remains UNCONFIRMED; company existence and clean searches do not authenticate the individual offer."
        )
        return OverallOutcome.NO_STRONG_RISK_SIGNALS, explanation

    def _compute_warning_strength(
        self,
        overall_outcome: OverallOutcome,
        strong_signals: List[WarningSignal],
        review_concerns: List[WarningSignal],
    ) -> Tuple[float, WarningBand]:
        """
        Computes an uncalibrated warning index (0.0 to 1.0).
        Never describes this as a fraud probability.
        Removes the artificial minimum of 0.05.
        """
        if overall_outcome == OverallOutcome.HIGH_RISK:
            # Bounded between 0.70 and 0.98
            score = 0.75
            for s in strong_signals:
                if s.code in ("CREDENTIAL_THEFT_DETECTED", "CREDENTIAL_THEFT_DEMAND"):
                    score = max(score, 0.95)
                elif s.code in ("UNLOCK_PAYMENT_DETECTED", "UNLOCK_PAYMENT_DEMAND"):
                    score = max(score, 0.90)
                elif s.code in ("ADVANCE_FEE_DETECTED", "UPFRONT_FEE_DEMAND"):
                    score = max(score, 0.85)
                elif s.code in ("ADVERSE_PHONE_REPORT", "ADVERSE_EMAIL_REPORT"):
                    score = max(score, 0.85)
                else:
                    score = max(score, 0.80)
            return round(score, 2), WarningBand.HIGH

        if overall_outcome == OverallOutcome.NEEDS_REVIEW:
            # Single review concern: 0.25; multiple: 0.35, capped at 0.40
            # Review concerns ALONE must NEVER cross 0.45 or reach HIGH_RISK
            if len(review_concerns) <= 1:
                score = 0.25
            else:
                score = 0.35
            return round(score, 2), WarningBand.MEDIUM

        # For CANNOT_VERIFY and NO_STRONG_RISK_SIGNALS:
        # Absence of supported warning signals has warning strength 0.0
        return 0.0, WarningBand.NONE

    def _compute_coverage_summary(
        self,
        checks: List[CheckCoverageItem],
        unresolved_issues: List[str],
    ) -> CoverageSummary:
        total = len(checks)
        applicable = [c for c in checks if c.applicability]
        completed = [c for c in applicable if c.execution_status == ExecutionStatus.COMPLETED]
        unavailable = [c for c in applicable if c.execution_status == ExecutionStatus.UNAVAILABLE]
        not_applicable = [c for c in checks if not c.applicability]

        app_count = len(applicable)
        comp_count = len(completed)
        unav_count = len(unavailable)
        na_count = len(not_applicable)

        ratio = round(comp_count / app_count, 2) if app_count > 0 else 0.0

        return CoverageSummary(
            total_checks=total,
            applicable_checks=app_count,
            completed_checks=comp_count,
            unavailable_checks=unav_count,
            not_applicable_checks=na_count,
            completion_ratio=ratio,
            unresolved_issues=unresolved_issues,
        )
