from typing import List, Tuple
from app.schemas.analysis import AgentFinding, RiskLevel
from app.core.logging import logger


class RiskEngine:
    """
    Synthesizes findings from CompanyAgent, RecruiterAgent, SalaryAgent, and ScamAgent.
    Computes a transparent, evidence-weighted risk score and determines risk tier:
      - VERIFIED: Consistent footprint, legitimate domain, no scam markers
      - NEEDS_REVIEW: Ambiguous recruiter presence, unverified domain, or salary outlier
      - HIGH_RISK: Advance fee demanded, free email for corporate role, or known scam match
    """

    def compute_risk(self, findings: List[AgentFinding]) -> Tuple[float, RiskLevel, List[str], List[str]]:
        logger.info("RiskEngine evaluating %d agent findings", len(findings))

        base_score = 0.0
        red_flags: List[str] = []
        green_flags: List[str] = []

        agent_map = {f.agent_name: f for f in findings}

        # 1. Scam Agent Weight (Highest priority)
        scam_finding = agent_map.get("ScamAgent")
        if scam_finding:
            if scam_finding.verdict == "HIGH_RISK":
                base_score += 0.50
                red_flags.append(scam_finding.summary)
            elif scam_finding.verdict == "VERIFIED":
                green_flags.append("No advance fee demands, security deposits, or OTP requests found.")

        # 2. Recruiter Agent Weight
        recruiter_finding = agent_map.get("RecruiterAgent")
        if recruiter_finding:
            if recruiter_finding.verdict == "HIGH_RISK":
                base_score += 0.35
                red_flags.append(recruiter_finding.summary)
            elif recruiter_finding.verdict == "NEEDS_REVIEW":
                base_score += 0.20
                red_flags.append(recruiter_finding.summary)
            else:
                green_flags.append("Recruiter credentials consistent with corporate domain standards.")

        # 3. Company Agent Weight
        company_finding = agent_map.get("CompanyAgent")
        if company_finding:
            if company_finding.verdict == "UNVERIFIED":
                base_score += 0.25
                red_flags.append(company_finding.summary)
            else:
                green_flags.append("Legitimate corporate registration and public web presence verified.")

        # 4. Salary Agent Weight
        salary_finding = agent_map.get("SalaryAgent")
        if salary_finding:
            if salary_finding.verdict == "NEEDS_REVIEW":
                base_score += 0.15
                red_flags.append(salary_finding.summary)
            else:
                green_flags.append("Compensation package falls within expected market baseline.")

        # Normalization (0.0 to 1.0)
        risk_score = min(max(round(base_score, 2), 0.05), 0.99)

        # Determine level
        if risk_score >= 0.50 or any("Critical scam" in f or "personal webmail" in f for f in red_flags):
            risk_level = RiskLevel.HIGH_RISK
        elif risk_score >= 0.25:
            risk_level = RiskLevel.NEEDS_REVIEW
        else:
            risk_level = RiskLevel.VERIFIED

        logger.info("Risk calculation complete: score=%.2f, level=%s", risk_score, risk_level.value)
        return risk_score, risk_level, red_flags, green_flags
