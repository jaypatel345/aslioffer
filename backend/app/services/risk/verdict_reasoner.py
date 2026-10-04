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
from app.services.report.presentation_helper import derive_reasons_and_details
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

        reasons, reason_details = derive_reasons_and_details(
            assessment=assessment,
            findings=findings,
            evidence_count=len(assessment.supporting_evidence_refs),
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

