from typing import Optional, List
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient
from app.core.logging import logger


class ScamAgent:
    """
    Investigates direct scam indicators, such as demands for upfront fees (laptop security,
    training fee, onboarding deposit), UPI payment requests, Telegram task groups, or
    known patterns flagged by CyberDost and NCRP.
    """

    def __init__(self, search_client: Optional[SerpApiClient] = None):
        self.search_client = search_client or SerpApiClient()

    async def investigate(
        self,
        company_name: str,
        demanded_fee: Optional[str],
        payment_method: Optional[str],
        flags: List[str],
        raw_text: str,
    ) -> AgentFinding:
        """
        Investigate scam markers and payment demands.
        Returns mocked investigation results for MVP.
        """
        logger.info(
            "ScamAgent checking for scam patterns: fee=%s, payment=%s",
            demanded_fee,
            payment_method,
        )

        evidence_list = []
        is_scam = bool(demanded_fee) or "DEMANDS_UPFRONT_FEE" in flags or "telegram" in raw_text.lower()

        if demanded_fee:
            evidence_list.append(
                EvidenceItem(
                    source_url="https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                    title="Advance Fee / Laptop Security Deposit Scam Warning",
                    description=f"Demand for '{demanded_fee}' violates Ministry of Labour regulations. Legitimate companies never charge applicants for equipment, screening, or training.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.99,
                )
            )

        if payment_method and payment_method.upper() in ["UPI", "GPAY", "PHONEPE", "PAYTM"]:
            evidence_list.append(
                EvidenceItem(
                    source_url="https://cybercrime.gov.in",
                    title="Direct UPI Payment Request Flag",
                    description=f"Instructions to transfer money via {payment_method} is a definitive characteristic of employment fraud in India.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.98,
                )
            )

        if "telegram" in raw_text.lower():
            evidence_list.append(
                EvidenceItem(
                    source_url="https://x.com/cyberdost",
                    title="CyberDost Advisory: Telegram Recruitment Fraud",
                    description="Official CyberDost advisory warns against employment communication conducted exclusively over Telegram task channels.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.90,
                )
            )

        if is_scam:
            return AgentFinding(
                agent_name="ScamAgent",
                verdict="HIGH_RISK",
                confidence=0.98,
                summary=f"Critical scam markers identified! Upfront fee demand ({demanded_fee or 'deposit'}) or suspicious channel detected.",
                evidence=evidence_list,
                details={
                    "demanded_fee": demanded_fee,
                    "payment_method": payment_method,
                    "scam_flagged": True,
                },
            )

        evidence_list.append(
            EvidenceItem(
                source_url="https://cybercrime.gov.in",
                title="No Upfront Fee or Scam Red Flags Detected",
                description="Offer does not solicit monetary deposits, training fees, or OTP/banking credentials.",
                evidence_type="SCAM_REPORT",
                confidence=0.90,
            )
        )

        return AgentFinding(
            agent_name="ScamAgent",
            verdict="VERIFIED",
            confidence=0.90,
            summary="No advance fee requests or known scam recruitment patterns detected in this offer.",
            evidence=evidence_list,
            details={"demanded_fee": None, "scam_flagged": False},
        )
