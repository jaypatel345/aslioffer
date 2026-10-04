from typing import List, Dict, Any, Optional, Set, Tuple
from app.schemas.analysis import AgentFinding, ExtractedEntities, VerdictReason, RiskLevel, EvidenceItem
from app.services.risk.assessment_models import (
    OverallOutcome,
    AuthenticityStatus,
    WarningSeverity,
    ExecutionStatus,
    ResolutionStatus,
    WarningSignal,
    CheckCoverageItem,
    StructuredAssessment,
)


def derive_green_flags(assessment: StructuredAssessment) -> List[str]:
    """
    Derives positive flags strictly grounded in completed, supported checks.
    Separates local document scanning from external complaint search.
    Never shows positive claims for unavailable or unexecuted checks.
    """
    flags: List[str] = []
    check_dict = {c.check_id: c for c in assessment.individual_checks}

    # 1. Local document scan (separated from external scam searches)
    local_scan = check_dict.get("LOCAL_DOCUMENT_SCAN")
    if (
        local_scan
        and local_scan.execution_status == ExecutionStatus.COMPLETED
        and local_scan.resolution_status == ResolutionStatus.NO_MATCH
    ):
        flags.append("Document text scan found no upfront fee demands, deposit requests, or credential solicitation.")

    # 2. External scam complaint search
    ext_scam = check_dict.get("EXTERNAL_SCAM_REPORTS")
    if (
        ext_scam
        and ext_scam.execution_status == ExecutionStatus.COMPLETED
        and ext_scam.resolution_status == ResolutionStatus.NO_MATCH
    ):
        flags.append("No matching scam or complaint reports found in external public search.")

    # 3. Company identity check
    comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
    if (
        comp_check
        and comp_check.execution_status == ExecutionStatus.COMPLETED
        and comp_check.resolution_status == ResolutionStatus.SUPPORTED
    ):
        flags.append("Claimed employer public web presence matched; registration status not independently checked.")

    # 4. Recruiter affiliation check
    rec_aff = check_dict.get("RECRUITER_AFFILIATION_CHECK")
    if (
        rec_aff
        and rec_aff.execution_status == ExecutionStatus.COMPLETED
        and rec_aff.resolution_status == ResolutionStatus.SUPPORTED
    ):
        flags.append("Recruiter email domain aligns with claimed corporate domain; does not prove mailbox control or hiring authority.")

    # 5. Compensation benchmark (only if completed and supported)
    sal_check = check_dict.get("COMPENSATION_BENCHMARK")
    if (
        sal_check
        and sal_check.execution_status == ExecutionStatus.COMPLETED
        and sal_check.resolution_status == ResolutionStatus.SUPPORTED
    ):
        flags.append("Offered compensation package falls within expected market baseline for role.")

    # Deduplicate deterministically preserving order
    deduped: List[str] = []
    seen = set()
    for f in flags:
        if f not in seen:
            seen.add(f)
            deduped.append(f)
    return deduped


def derive_official_company_info(
    findings: List[AgentFinding],
    company_name: str,
    assessment: Optional[StructuredAssessment] = None,
) -> Dict[str, Optional[str]]:
    """
    Extracts official company information strictly from supported CompanyAgent findings.
    Does not promote document-provided links or unverified domains.
    Handles conflicting company findings conservatively and deterministically.
    """
    clean_name = company_name.strip() if company_name else "Company"

    company_findings = [f for f in findings if f.agent_name == "CompanyAgent"]

    official_domain: Optional[str] = None
    careers_url: Optional[str] = None

    if company_findings:
        verdicts = {f.verdict for f in company_findings}
        verified_domains: Set[str] = set()
        verified_careers: Set[str] = set()
        has_supported_finding = False

        for f in company_findings:
            det = f.details or {}
            dom = det.get("official_domain")
            car = det.get("careers_url")
            p_status = det.get("provider_status", "SUCCESS")
            if f.verdict == "VERIFIED" and p_status == "SUCCESS" and dom:
                verified_domains.add(dom)
                if car:
                    verified_careers.add(car)
                has_supported_finding = True

        # If verdicts conflict (e.g. one VERIFIED and one HIGH_RISK or CANNOT_VERIFY)
        # or multiple distinct official_domain values exist, handle conservatively
        if len(verdicts) > 1 or len(verified_domains) > 1:
            official_domain = None
            careers_url = None
        elif len(verified_domains) == 1 and has_supported_finding:
            if assessment:
                comp_check = next((c for c in assessment.individual_checks if c.check_id == "COMPANY_IDENTITY_CHECK"), None)
                if comp_check and comp_check.resolution_status == ResolutionStatus.SUPPORTED:
                    official_domain = sorted(list(verified_domains))[0]
                    careers_url = sorted(list(verified_careers))[0] if verified_careers else None
                else:
                    official_domain = None
                    careers_url = None
            else:
                official_domain = sorted(list(verified_domains))[0]
                careers_url = sorted(list(verified_careers))[0] if verified_careers else None

    return {
        "name": clean_name,
        "website": official_domain,
        "careers_url": careers_url,
        "mca_status": "Not independently checked",
        "recruitment_policy": "Not independently checked",
    }


def derive_summary(
    assessment: StructuredAssessment,
    company_name: str,
    extracted_entities: Optional[ExtractedEntities] = None,
) -> str:
    """
    Generates outcome-specific summaries grounded in structured assessment findings,
    signals, coverage gaps, and unauthenticated offer status.
    """
    comp_name = company_name.strip() if company_name else "Company"
    check_dict = {c.check_id: c for c in assessment.individual_checks}
    unconfirmed_notice = "The employer has not authenticated this individual offer; public web checks cannot verify offer issuance."

    if assessment.overall_outcome == OverallOutcome.HIGH_RISK:
        signal_descriptions = [s.description for s in assessment.supported_warning_signals]
        headline = signal_descriptions[0] if signal_descriptions else "Critical adverse signals detected"
        extra = f" ({len(signal_descriptions) - 1} further critical signal(s) detected)" if len(signal_descriptions) > 1 else ""

        gap_notes = []
        unavailable = [c.check_name for c in assessment.individual_checks if c.execution_status == ExecutionStatus.UNAVAILABLE]
        if unavailable:
            gap_notes.append(f"external checks ({', '.join(unavailable[:2])}) were unavailable due to provider outages")
        elif assessment.unresolved_issues:
            gap_notes.append(f"coverage gaps remain ({assessment.unresolved_issues[0]})")

        gap_str = f" Note that {'; '.join(gap_notes)}, but the detected signals warrant immediate caution." if gap_notes else ""

        return (
            f"HIGH RISK: This offer contains critical warning signals: {headline}{extra}. "
            f"While this assessment does not constitute formal legal proof of fraud, such demands are characteristic of employment fraud.{gap_str} "
            f"{unconfirmed_notice}"
        )

    elif assessment.overall_outcome == OverallOutcome.NEEDS_REVIEW:
        concerns = [c.description for c in assessment.review_only_concerns]
        concern_str = "; ".join(concerns) if concerns else "Contextual offer parameters require independent confirmation."

        comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
        if comp_check and comp_check.resolution_status == ResolutionStatus.SUPPORTED:
            comp_status = f"While public web records were found for {comp_name}, {concern_str}"
        elif comp_check and comp_check.execution_status == ExecutionStatus.UNAVAILABLE:
            comp_status = f"Employer verification was unavailable due to service outages, and {concern_str}"
        elif comp_check and comp_check.resolution_status == ResolutionStatus.NO_MATCH:
            comp_status = f"No public records were found for {comp_name}, and {concern_str}"
        else:
            comp_status = f"Employer public footprint could not be confirmed, and {concern_str}"

        gap_notes = []
        if assessment.unresolved_issues:
            gap_notes.append(assessment.unresolved_issues[0])
        gap_str = f" Unresolved items: {'; '.join(gap_notes)}." if gap_notes else ""

        return (
            f"NEEDS MANUAL REVIEW: Key aspects of this offer require human review. "
            f"{comp_status}.{gap_str} "
            f"{unconfirmed_notice}"
        )

    elif assessment.overall_outcome == OverallOutcome.CANNOT_VERIFY:
        reasons_list = []
        unavailable_checks = [c.check_name for c in assessment.individual_checks if c.execution_status == ExecutionStatus.UNAVAILABLE]
        no_match_checks = [c.check_name for c in assessment.individual_checks if c.execution_status == ExecutionStatus.COMPLETED and c.resolution_status == ResolutionStatus.NO_MATCH]
        not_checked_checks = [c.check_name for c in assessment.individual_checks if c.execution_status == ExecutionStatus.NOT_CHECKED and c.applicability]

        if unavailable_checks:
            reasons_list.append(f"External search checks ({', '.join(unavailable_checks[:2])}) were unavailable due to service outages")
        if no_match_checks:
            reasons_list.append(f"Public searches completed but found no matching records ({', '.join(no_match_checks[:2])})")
        if not_checked_checks:
            reasons_list.append(f"Essential contact information was missing or checks were not executed ({', '.join(not_checked_checks[:2])})")
        if not reasons_list:
            reasons_list.append("Some checks were unavailable or did not establish sufficient evidence")

        reasons_str = "; ".join(reasons_list)

        return (
            f"INCONCLUSIVE PUBLIC EVIDENCE: Could not independently verify this offer from available evidence. "
            f"Some checks were unavailable or did not establish sufficient evidence ({reasons_str}). "
            f"Inconclusive evidence is not proof of fraud, but means the offer cannot be substantiated through public channels. "
            f"{unconfirmed_notice}"
        )

    else:  # NO_STRONG_RISK_SIGNALS
        positive_items = []
        comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
        if comp_check and comp_check.resolution_status == ResolutionStatus.SUPPORTED:
            positive_items.append(f"public web records for {comp_name} were matched")

        rec_aff = check_dict.get("RECRUITER_AFFILIATION_CHECK")
        if rec_aff and rec_aff.resolution_status == ResolutionStatus.SUPPORTED:
            positive_items.append("recruiter email domain aligns with corporate domain")

        sal_check = check_dict.get("COMPENSATION_BENCHMARK")
        if sal_check and sal_check.execution_status == ExecutionStatus.COMPLETED and sal_check.resolution_status == ResolutionStatus.SUPPORTED:
            positive_items.append("compensation aligns with market baseline")

        pos_str = f" ({', '.join(positive_items)})" if positive_items else ""

        return (
            f"NO STRONG RISK SIGNALS: Completed checks found no supported adverse signals or active scam indicators{pos_str}. "
            f"Note: {unconfirmed_notice} Public web consistency does not prove that this document was legitimately issued."
        )


def derive_reasons_and_details(
    assessment: StructuredAssessment,
    findings: Optional[List[AgentFinding]] = None,
    evidence_count: int = 0,
) -> Tuple[List[str], List[VerdictReason]]:
    """
    Derives canonical reasons and VerdictReason items from the structured assessment.
    Preserves signal codes, includes concrete coverage gaps across all outcomes,
    avoids generic invented anomalies, and uses evidence observation wording.
    """
    reasons: List[str] = []
    reason_details: List[VerdictReason] = []
    check_dict = {c.check_id: c for c in assessment.individual_checks}

    if assessment.overall_outcome == OverallOutcome.HIGH_RISK:
        for s in assessment.supported_warning_signals:
            reasons.append(s.description)
            reason_details.append(VerdictReason(code=s.code, reason=s.description))

        for c in assessment.review_only_concerns:
            reasons.append(c.description)
            code = "PERSONAL_EMAIL_DOMAIN" if c.code == "FREE_WEBMAIL_DOMAIN" else c.code
            reason_details.append(VerdictReason(code=code, reason=c.description))

        # Include concrete coverage gaps even in HIGH_RISK
        comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
        if comp_check and comp_check.resolution_status != ResolutionStatus.SUPPORTED:
            if comp_check.execution_status == ExecutionStatus.UNAVAILABLE:
                msg = "Company identity verification was unavailable due to search service outage."
                code = "COMPANY_SEARCH_UNAVAILABLE"
            else:
                msg = "No established public corporate footprint verified for company."
                code = "COMPANY_NOT_VERIFIED"
            reasons.append(msg)
            reason_details.append(VerdictReason(code=code, reason=msg))

        rec_rep = check_dict.get("RECRUITER_CONTACT_REPUTATION")
        rec_aff = check_dict.get("RECRUITER_AFFILIATION_CHECK")
        if (
            (rec_rep and rec_rep.execution_status in (ExecutionStatus.NOT_CHECKED, ExecutionStatus.UNAVAILABLE))
            or (rec_aff and rec_aff.resolution_status != ResolutionStatus.SUPPORTED)
        ):
            msg = "Recruiter identity could not be independently confirmed."
            reasons.append(msg)
            reason_details.append(VerdictReason(code="RECRUITER_NOT_VERIFIED", reason=msg))

    elif assessment.overall_outcome == OverallOutcome.NEEDS_REVIEW:
        for c in assessment.review_only_concerns:
            reasons.append(c.description)
            code = "PERSONAL_EMAIL_DOMAIN" if c.code == "FREE_WEBMAIL_DOMAIN" else c.code
            reason_details.append(VerdictReason(code=code, reason=c.description))

        # Include concrete coverage gaps in NEEDS_REVIEW
        comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
        if comp_check and comp_check.resolution_status != ResolutionStatus.SUPPORTED:
            if comp_check.execution_status == ExecutionStatus.UNAVAILABLE:
                msg = "Company identity verification was unavailable due to search service outage."
                code = "COMPANY_SEARCH_UNAVAILABLE"
            else:
                msg = "No established public corporate footprint verified for company."
                code = "COMPANY_NOT_VERIFIED"
            reasons.append(msg)
            reason_details.append(VerdictReason(code=code, reason=msg))

        rec_rep = check_dict.get("RECRUITER_CONTACT_REPUTATION")
        rec_aff = check_dict.get("RECRUITER_AFFILIATION_CHECK")
        if (
            (rec_rep and rec_rep.execution_status in (ExecutionStatus.NOT_CHECKED, ExecutionStatus.UNAVAILABLE))
            or (rec_aff and rec_aff.resolution_status != ResolutionStatus.SUPPORTED)
        ):
            msg = "Recruiter identity could not be independently confirmed."
            reasons.append(msg)
            reason_details.append(VerdictReason(code="RECRUITER_NOT_VERIFIED", reason=msg))

        if findings and not assessment.review_only_concerns and any(f.verdict == "NEEDS_REVIEW" for f in findings):
            msg = "Certain offer parameters require independent corporate confirmation."
            reasons.append(msg)
            reason_details.append(VerdictReason(code="NEEDS_MANUAL_CONFIRMATION", reason=msg))

    elif assessment.overall_outcome == OverallOutcome.CANNOT_VERIFY:
        msg = "Could not independently verify this offer from available evidence."
        reasons.append(msg)

        if evidence_count == 0:
            reason_details.append(
                VerdictReason(
                    code="NO_PUBLIC_EVIDENCE",
                    reason="No verifiable public evidence available for this offer.",
                )
            )
        else:
            reason_details.append(
                VerdictReason(
                    code="INSUFFICIENT_SEARCH_RESULTS",
                    reason=f"Public evidence is insufficient ({evidence_count} evidence observation(s)).",
                )
            )

        comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
        if comp_check and comp_check.resolution_status != ResolutionStatus.SUPPORTED:
            if comp_check.execution_status == ExecutionStatus.UNAVAILABLE:
                comp_msg = "Company identity verification was unavailable due to search service outage."
                code = "COMPANY_SEARCH_UNAVAILABLE"
            else:
                comp_msg = "No established public corporate footprint verified for company."
                code = "COMPANY_NOT_VERIFIED"
            reasons.append(comp_msg)
            reason_details.append(VerdictReason(code=code, reason=comp_msg))

        rec_rep = check_dict.get("RECRUITER_CONTACT_REPUTATION")
        rec_aff = check_dict.get("RECRUITER_AFFILIATION_CHECK")
        if (
            (rec_rep and rec_rep.execution_status in (ExecutionStatus.NOT_CHECKED, ExecutionStatus.UNAVAILABLE))
            or (rec_aff and rec_aff.resolution_status != ResolutionStatus.SUPPORTED)
        ):
            rec_msg = "Recruiter identity could not be independently confirmed."
            reasons.append(rec_msg)
            reason_details.append(VerdictReason(code="RECRUITER_NOT_VERIFIED", reason=rec_msg))

        for c in assessment.review_only_concerns:
            reasons.append(c.description)
            code = "PERSONAL_EMAIL_DOMAIN" if c.code == "FREE_WEBMAIL_DOMAIN" else c.code
            reason_details.append(VerdictReason(code=code, reason=c.description))

    else:  # NO_STRONG_RISK_SIGNALS (VERIFIED)
        msg = "Offer credentials align with verified corporate footprint and public records."
        reasons.append(msg)
        reason_details.append(
            VerdictReason(
                code="LEGITIMATE_FOOTPRINT_VERIFIED",
                reason=msg,
            )
        )
        reason_details.append(
            VerdictReason(
                code="CLEAN_RECRUITMENT_RECORDS",
                reason="No advance fees, deposits, or scam recruitment indicators detected.",
            )
        )
        reason_details.append(
            VerdictReason(
                code="OFFER_AUTHENTICITY_UNCONFIRMED",
                reason="Public web presence confirmed; individual offer authenticity remains unconfirmed.",
            )
        )

    deduped_reasons: List[str] = []
    seen_reasons = set()
    for r in reasons:
        if r not in seen_reasons:
            seen_reasons.add(r)
            deduped_reasons.append(r)

    deduped_details: List[VerdictReason] = []
    seen_details = set()
    for d in reason_details:
        key = (d.code, d.reason)
        if key not in seen_details:
            seen_details.add(key)
            deduped_details.append(d)

    return deduped_reasons, deduped_details


def derive_recommended_actions(
    assessment: StructuredAssessment,
    extracted_entities: Optional[ExtractedEntities] = None,
) -> List[str]:
    """
    Selects and deduplicates recommended actions grounded in actual signals,
    review concerns, and investigation gaps. Avoids over-reaction, misleading claims,
    and invented verification mechanisms.
    """
    actions: List[str] = []
    signal_codes = {s.code for s in assessment.supported_warning_signals}
    concern_codes = {c.code for c in assessment.review_only_concerns}
    check_dict = {c.check_id: c for c in assessment.individual_checks}

    # 1. Active fee / deposit / unlock demand
    fee_signals = {"ADVANCE_FEE_DETECTED", "UPFRONT_FEE_DEMAND", "UNLOCK_PAYMENT_DETECTED", "UNLOCK_PAYMENT_DEMAND"}
    if signal_codes & fee_signals:
        actions.append("DO NOT pay any registration fee, security deposit, laptop charge, or document processing fee under any circumstance.")
        actions.append("Verify payment policies directly with the employer's official HR department; legitimate employers in India do not charge hiring fees.")

    # 2. Candidate payment request (UPI/mobile wallet without confirmed fee demand)
    if "CANDIDATE_PAYMENT_DETECTED" in concern_codes:
        actions.append("Do not transfer money via UPI, payment links, or mobile wallets for onboarding or training expenses.")

    # 3. Credential theft (bank OTP, password, net banking)
    credential_signals = {"CREDENTIAL_THEFT_DETECTED", "CREDENTIAL_THEFT_DEMAND"}
    if signal_codes & credential_signals:
        actions.append("DO NOT disclose banking passwords, OTPs, UPI PINs, or net banking credentials; legitimate employers never require account credentials.")

    # 4. Adverse contact reports (phone/email in public scam records)
    adverse_contact_signals = {"ADVERSE_PHONE_REPORT", "ADVERSE_EMAIL_REPORT"}
    if signal_codes & adverse_contact_signals:
        actions.append("Cease communication through the flagged recruiter contact number or email address, as it appears in public complaint reports.")

    # 5. Conditional cybercrime reporting guidance (only for high-risk / suspected fraud)
    if assessment.overall_outcome == OverallOutcome.HIGH_RISK:
        actions.append("If you suspect employment fraud or have experienced financial loss or credential theft, report the incident to the National Cyber Crime Reporting Portal at https://cybercrime.gov.in or call helpline 1930.")

    # 6. Recruiter domain mismatch or free webmail
    domain_concerns = {"FREE_WEBMAIL_DOMAIN", "PERSONAL_EMAIL_DOMAIN", "RECRUITER_DOMAIN_MISMATCH"}
    if concern_codes & domain_concerns:
        actions.append("The recruiter contacted you from a personal or non-matching email domain. Request written communication from the employer's official corporate email domain.")
        actions.append("Independently confirm the recruiter's hiring authority by calling the employer's official corporate switchboard or published HR directory.")

    # 7. Staffing agency mandate or affiliation unconfirmed
    agency_concerns = {"AGENCY_MANDATE_UNCONFIRMED", "AGENCY_AFFILIATION_UNCONFIRMED"}
    if concern_codes & agency_concerns:
        actions.append("Confirm the staffing agency's authorization and candidate representation mandate directly with the client employer's HR department.")

    # 8. Salary outlier / compensation ambiguity
    if "SALARY_OUTLIER" in concern_codes:
        actions.append("Request written clarification from the employer regarding total compensation, currency, payment frequency, and employment terms.")

    # 9. Provider outages
    unavailable_checks = [c.check_name for c in assessment.individual_checks if c.execution_status == ExecutionStatus.UNAVAILABLE]
    if unavailable_checks:
        actions.append(f"External search checks ({', '.join(unavailable_checks[:2])}) were unavailable due to service outages; re-run verification or check official records independently.")

    # 10. Missing employer verification / public footprint
    comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
    if comp_check and comp_check.resolution_status != ResolutionStatus.SUPPORTED:
        actions.append("Independently look up the employer using official public business registries (such as MCA India at mca.gov.in) or verified business directories.")
        actions.append("Do not rely on website links, phone numbers, or addresses provided solely within the submitted document.")

    # 11. Universal next steps for non-high-risk offers (authenticity verification & employment terms)
    if assessment.overall_outcome != OverallOutcome.HIGH_RISK:
        actions.append("Contact the employer directly through their official published careers portal or HR department to confirm that this specific offer was issued to you.")
        actions.append("Review standard employment terms, scope of work, and contract conditions carefully before signing.")
        actions.append("Never share sensitive banking passwords, OTPs, or pay any onboarding charges.")

    # Deduplicate deterministically preserving order
    deduped: List[str] = []
    seen = set()
    for a in actions:
        if a not in seen:
            seen.add(a)
            deduped.append(a)

    return deduped
