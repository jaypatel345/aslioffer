from typing import List, Dict, Any, Optional, Union
from app.schemas.analysis import (
    RiskLevel,
    AgentFinding,
    EvidenceItem,
    VerdictReason,
    VerdictResult,
)
from app.core.logging import logger


class VerdictReasoner:
    """
    Evidence-aware verdict reasoning layer.
    Sits after the deterministic RiskEngine and evaluates evidence quantity and quality:
      Risk Engine -> Verdict Reasoner -> Verification Report

    Determines final verdict:
      - HIGH_RISK: Advance fee, spoofed recruiter, or risk_score >= 0.50
      - CANNOT_VERIFY: Insufficient evidence (evidence_count < 2 or avg_confidence < 0.60) with no scam indicators
      - NEEDS_REVIEW: Salary anomaly or ambiguous credentials
      - VERIFIED: Consistent corporate presence and verified recruiter credentials with adequate evidence
    """

    CONFIDENCE_THRESHOLD: float = 0.60
    MIN_EVIDENCE_COUNT: int = 2

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

        # 1. Collect all evidence items
        all_evidence: List[EvidenceItem] = []
        for f in findings:
            all_evidence.extend(f.evidence)

        # 2. Documented Confidence Formula:
        # evidence_strength = min(evidence_count / 4.0, 1.0)
        # confidence = round((average_agent_confidence + evidence_strength) / 2.0, 2)
        avg_agent_conf = sum(f.confidence for f in findings) / len(findings) if findings else 0.0
        evidence_count = len(all_evidence)
        evidence_strength = min(evidence_count / 4.0, 1.0)

        # Also check evidence-level average confidence
        avg_evidence_conf = (
            sum(e.confidence for e in all_evidence) / evidence_count if evidence_count > 0 else 0.0
        )

        overall_confidence = round((avg_agent_conf + evidence_strength) / 2.0, 2)

        # 3. Assess Insufficient Evidence Condition:
        # Evidence count < 2 OR avg_confidence < 0.60
        insufficient_evidence = (
            evidence_count < self.MIN_EVIDENCE_COUNT or avg_evidence_conf < self.CONFIDENCE_THRESHOLD
        )

        reasons: List[str] = []
        reason_details: List[VerdictReason] = []

        # 4. Check for High-Risk Scam Markers first
        has_scam_markers = (
            scam.verdict == "HIGH_RISK"
            or rec.verdict == "HIGH_RISK"
            or initial_risk_score >= 0.50
        )

        if has_scam_markers:
            verdict = RiskLevel.HIGH_RISK

            if scam.verdict == "HIGH_RISK":
                reasons.append(scam.summary)
                reason_details.append(
                    VerdictReason(
                        code="ADVANCE_FEE_DETECTED",
                        reason=scam.summary,
                    )
                )

            if rec.verdict == "HIGH_RISK":
                reasons.append(rec.summary)
                reason_details.append(
                    VerdictReason(
                        code="PERSONAL_EMAIL_DOMAIN",
                        reason=rec.summary,
                    )
                )

        # 5. Check for Cannot Verify (insufficient evidence and no scam markers)
        elif insufficient_evidence:
            verdict = RiskLevel.CANNOT_VERIFY
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
                        reason=f"Public evidence is insufficient ({evidence_count} source(s), avg confidence {avg_evidence_conf:.2f}).",
                    )
                )

            if comp.verdict == "UNVERIFIED":
                comp_msg = f"No established public corporate footprint verified for company."
                reasons.append(comp_msg)
                reason_details.append(
                    VerdictReason(
                        code="COMPANY_NOT_VERIFIED",
                        reason=comp_msg,
                    )
                )

            if rec.verdict == "UNVERIFIED":
                rec_msg = "Recruiter identity could not be independently confirmed."
                reasons.append(rec_msg)
                reason_details.append(
                    VerdictReason(
                        code="RECRUITER_NOT_VERIFIED",
                        reason=rec_msg,
                    )
                )

        # 6. Check for Anomaly / Needs Review
        elif sal.verdict == "NEEDS_REVIEW" or comp.verdict == "NEEDS_REVIEW" or initial_risk_score >= 0.25:
            verdict = RiskLevel.NEEDS_REVIEW

            if sal.verdict == "NEEDS_REVIEW":
                reasons.append(sal.summary)
                reason_details.append(
                    VerdictReason(
                        code="SALARY_OUTLIER",
                        reason=sal.summary,
                    )
                )

            if comp.verdict == "UNVERIFIED" or comp.verdict == "NEEDS_REVIEW":
                reasons.append(comp.summary)
                reason_details.append(
                    VerdictReason(
                        code="COMPANY_NOT_VERIFIED",
                        reason=comp.summary,
                    )
                )
            else:
                reasons.append("Certain offer parameters require independent corporate confirmation.")
                reason_details.append(
                    VerdictReason(
                        code="NEEDS_MANUAL_CONFIRMATION",
                        reason="Ambiguous credentials or salary outliers require manual confirmation.",
                    )
                )

        # 7. Otherwise Verified
        else:
            verdict = RiskLevel.VERIFIED
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

        logger.info(
            "VerdictReasoner determined verdict=%s (confidence=%.2f, evidence_count=%d)",
            verdict.value,
            overall_confidence,
            evidence_count,
        )

        return VerdictResult(
            verdict=verdict,
            confidence=overall_confidence,
            reasons=reasons,
            reason_details=reason_details,
            evidence=all_evidence,
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
                verdict=finding_input.get("verdict", "VERIFIED"),
                confidence=float(finding_input.get("confidence", 0.8)),
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
