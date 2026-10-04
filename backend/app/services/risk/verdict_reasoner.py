from typing import List, Dict, Any, Optional, Union
from app.schemas.analysis import (
    RiskLevel,
    AgentFinding,
    EvidenceItem,
    VerdictReason,
    VerdictResult,
)
from app.services.risk.assessment_engine import AssessmentEngine, canonicalize_url
from app.services.risk.assessment_models import (
    OverallOutcome,
    ExecutionStatus,
    ResolutionStatus,
    StructuredAssessment,
)
from app.core.logging import logger


class VerdictReasoner:
    """
    Evidence-aware verdict reasoning layer.
    Delegates to the unified AssessmentEngine (Task 8) so RiskEngine and VerdictReasoner
    never reach contradictory outcomes.
    
    Categorical outcome precedence:
      - HIGH_RISK: Supported strong adverse signals (advance fees, credential theft, adverse reports)
      - NEEDS_REVIEW: Supported contextual review concerns (domain mismatch, personal email, salary anomaly)
      - CANNOT_VERIFY: Inconclusive public evidence, provider outages, or missing essential contacts
      - NO_STRONG_RISK_SIGNALS (legacy VERIFIED): Consistent public footprint, clean scam searches;
        authenticity status strictly UNCONFIRMED (public searches do not authenticate individual offers).
    """

    CONFIDENCE_THRESHOLD: float = 0.60
    MIN_EVIDENCE_COUNT: int = 2

    def __init__(self, assessment_engine: Optional[AssessmentEngine] = None):
        self.engine = assessment_engine or AssessmentEngine()

    def evaluate(
        self,
        company_result: Union[AgentFinding, Dict[str, Any]],
        recruiter_result: Union[AgentFinding, Dict[str, Any]],
        salary_result: Union[AgentFinding, Dict[str, Any]],
        scam_result: Union[AgentFinding, Dict[str, Any]],
        initial_risk_score: float,
        initial_risk_level: Optional[RiskLevel] = None,
    ) -> VerdictResult:
        logger.info("VerdictReasoner evaluating agent findings with initial risk_score=%.2f", initial_risk_score)

        # Normalize inputs to AgentFinding objects if dicts were passed
        comp = self._ensure_finding("CompanyAgent", company_result)
        rec = self._ensure_finding("RecruiterAgent", recruiter_result)
        sal = self._ensure_finding("SalaryAgent", salary_result)
        scam = self._ensure_finding("ScamAgent", scam_result)

        findings = [comp, rec, sal, scam]

        # Unified assessment
        assessment = self.engine.assess(findings)

        # Deduplicate evidence items
        seen_keys = set()
        deduped_evidence: List[EvidenceItem] = []
        safe_findings, _ = self.engine._normalize_findings(findings)
        for f in safe_findings:
            for ev in f.evidence:
                canon_url = canonicalize_url(ev.source_url)
                title_key = (ev.title or "").strip().lower()
                key = (canon_url, title_key, ev.description, ev.evidence_type)
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped_evidence.append(ev)

        evidence_count = len(deduped_evidence)

        # Map outcome to legacy RiskLevel
        outcome_map = {
            OverallOutcome.HIGH_RISK: RiskLevel.HIGH_RISK,
            OverallOutcome.NEEDS_REVIEW: RiskLevel.NEEDS_REVIEW,
            OverallOutcome.CANNOT_VERIFY: RiskLevel.CANNOT_VERIFY,
            OverallOutcome.NO_STRONG_RISK_SIGNALS: RiskLevel.VERIFIED,
        }
        verdict = outcome_map[assessment.overall_outcome]

        # Conservative confidence calculation:
        # Categorical evidence strength; does NOT describe confidence in offer authenticity.
        # Repeated sources or duplicated findings do not inflate confidence.
        if verdict == RiskLevel.HIGH_RISK:
            confidence = 0.95
        elif verdict == RiskLevel.NEEDS_REVIEW:
            confidence = 0.85
        elif verdict == RiskLevel.CANNOT_VERIFY:
            confidence = 0.0 if evidence_count == 0 else 0.35
        else:  # VERIFIED / NO_STRONG_RISK_SIGNALS
            # Sufficient applicable checks completed cleanly
            ratio = assessment.coverage_summary.completion_ratio
            confidence = round(0.70 + (ratio * 0.15), 2)

        reasons: List[str] = []
        reason_details: List[VerdictReason] = []
        check_dict = {c.check_id: c for c in assessment.individual_checks}

        if verdict == RiskLevel.HIGH_RISK:
            for s in assessment.supported_warning_signals:
                reasons.append(s.description)
                reason_details.append(VerdictReason(code=s.code, reason=s.description))
            # Include any co-occurring review concerns (e.g. personal email domain)
            for c in assessment.review_only_concerns:
                reasons.append(c.description)
                reason_code = "PERSONAL_EMAIL_DOMAIN" if c.code == "FREE_WEBMAIL_DOMAIN" else c.code
                reason_details.append(VerdictReason(code=reason_code, reason=c.description))

        elif verdict == RiskLevel.NEEDS_REVIEW:
            for c in assessment.review_only_concerns:
                reasons.append(c.description)
                reason_code = "PERSONAL_EMAIL_DOMAIN" if c.code == "FREE_WEBMAIL_DOMAIN" else c.code
                reason_details.append(VerdictReason(code=reason_code, reason=c.description))
            # Retain visibility of coverage gaps
            if not any(f.verdict == "NEEDS_REVIEW" for f in findings):
                reasons.append("Certain offer parameters require independent corporate confirmation.")
                reason_details.append(
                    VerdictReason(
                        code="NEEDS_MANUAL_CONFIRMATION",
                        reason="Ambiguous credentials or salary outliers require manual confirmation.",
                    )
                )

        elif verdict == RiskLevel.CANNOT_VERIFY:
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
                        reason=f"Public evidence is insufficient ({evidence_count} unique source(s)).",
                    )
                )

            comp_check = check_dict.get("COMPANY_IDENTITY_CHECK")
            if comp_check and comp_check.resolution_status != ResolutionStatus.SUPPORTED:
                comp_msg = "No established public corporate footprint verified for company."
                reasons.append(comp_msg)
                reason_details.append(
                    VerdictReason(
                        code="COMPANY_NOT_VERIFIED",
                        reason=comp_msg,
                    )
                )

            rec_rep = check_dict.get("RECRUITER_CONTACT_REPUTATION")
            rec_aff = check_dict.get("RECRUITER_AFFILIATION_CHECK")
            if (rec_rep and rec_rep.execution_status == ExecutionStatus.NOT_CHECKED) or (
                rec_aff and rec_aff.resolution_status != ResolutionStatus.SUPPORTED
            ):
                rec_msg = "Recruiter identity could not be independently confirmed."
                reasons.append(rec_msg)
                reason_details.append(
                    VerdictReason(
                        code="RECRUITER_NOT_VERIFIED",
                        reason=rec_msg,
                    )
                )

            # Preserve review concerns if any were noted (do not drop them merely because coverage is inconclusive)
            for c in assessment.review_only_concerns:
                reasons.append(c.description)
                reason_code = "PERSONAL_EMAIL_DOMAIN" if c.code == "FREE_WEBMAIL_DOMAIN" else c.code
                reason_details.append(VerdictReason(code=reason_code, reason=c.description))

        else:  # VERIFIED (NO_STRONG_RISK_SIGNALS)
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

        logger.info(
            "VerdictReasoner determined verdict=%s (confidence=%.2f, evidence_count=%d)",
            verdict.value,
            confidence,
            evidence_count,
        )

        return VerdictResult(
            verdict=verdict,
            confidence=confidence,
            reasons=reasons,
            reason_details=reason_details,
            evidence=deduped_evidence,
            overall_outcome=assessment.overall_outcome,
            authenticity_status=assessment.authenticity_status,
            warning_strength=assessment.warning_strength,
            warning_band=assessment.warning_band,
            structured_assessment=assessment,
        )

    def _ensure_finding(self, agent_name: str, finding_input: Union[AgentFinding, Dict[str, Any]]) -> AgentFinding:
        if isinstance(finding_input, AgentFinding):
            return finding_input
        if isinstance(finding_input, dict):
            evidence_items = []
            for ev in finding_input.get("evidence", []):
                if isinstance(ev, EvidenceItem):
                    evidence_items.append(ev)
                elif isinstance(ev, dict):
                    evidence_items.append(EvidenceItem(**ev))
            return AgentFinding(
                agent_name=finding_input.get("agent_name", agent_name),
                verdict=finding_input.get("verdict", "CANNOT_VERIFY"),
                confidence=float(finding_input.get("confidence", 0.0)),
                summary=finding_input.get("summary", ""),
                evidence=evidence_items,
                details=finding_input.get("details", {}),
            )
        # Fallback default
        return AgentFinding(
            agent_name=agent_name,
            verdict="VERIFIED",
            confidence=0.8,
            summary=f"{agent_name} default finding",
            evidence=[],
            details={},
        )

