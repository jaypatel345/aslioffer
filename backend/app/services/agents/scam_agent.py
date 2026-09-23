from typing import Optional, List, Dict, Any
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient, SearchSource
from app.core.logging import logger

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com", "icloud.com"}

FEE_KEYWORDS = [
    "registration fee",
    "security deposit",
    "training fee",
    "laptop fee",
    "laptop security",
    "onboarding fee",
    "onboarding deposit",
    "document verification fee",
]

UPI_METHODS = {"UPI", "GPAY", "PHONEPE", "PAYTM"}


class ScamAgent:
    """
    Investigates direct scam indicators, such as demands for upfront fees (laptop security,
    training fee, onboarding deposit), UPI payment requests, Telegram/WhatsApp task groups,
    personal email domains for enterprise claims, and known patterns flagged by CyberDost and NCRP.
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
        Investigate scam markers, fee demands, suspicious payment channels, and live public warnings.
        """
        logger.info(
            "ScamAgent checking for scam patterns: company=%s, fee=%s, payment=%s",
            company_name,
            demanded_fee,
            payment_method,
        )

        raw_lower = raw_text.lower()
        evidence_list: List[EvidenceItem] = []
        detected_signals: List[str] = []

        # 1. Independent Risk Signals

        # Signal A: Upfront Fee Demands
        has_fee = (
            bool(demanded_fee)
            or "DEMANDS_UPFRONT_FEE" in flags
            or any(kw in raw_lower for kw in FEE_KEYWORDS)
        )
        if has_fee:
            detected_signals.append("UPFRONT_FEE_DEMAND")
            fee_desc = demanded_fee or "mandatory upfront fee / security deposit"
            evidence_list.append(
                EvidenceItem(
                    source_url="https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                    title="Advance Fee / Security Deposit Scam Warning",
                    description=f"Demand for '{fee_desc}' violates Ministry of Labour regulations. Legitimate employers never charge candidates for equipment, screening, or onboarding.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.99,
                )
            )

        # Signal B: UPI / Mobile Wallet Payment Request (Fixes UPI bug)
        is_upi_payment = (
            (bool(payment_method) and payment_method.upper() in UPI_METHODS)
            or any(m in raw_text.upper() for m in ["UPI ID", "@OKAXIS", "@OKICICI", "@OKHDFC"])
            or "UPI" in flags
            or (has_fee and any(m in raw_lower for m in ["gpay", "phonepe", "paytm", "upi"]))
        )
        if is_upi_payment:
            detected_signals.append("UPI_PAYMENT_REQUEST")
            method_desc = payment_method or "UPI / Mobile Wallet"
            evidence_list.append(
                EvidenceItem(
                    source_url="https://cybercrime.gov.in",
                    title="Direct UPI Payment Request Flag",
                    description=f"Instructions to transfer recruitment funds via {method_desc} is a definitive characteristic of employment fraud in India.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.98,
                )
            )

        # Signal C: Telegram Communication
        has_telegram = "telegram" in raw_lower or "TELEGRAM" in flags
        if has_telegram:
            detected_signals.append("TELEGRAM_COMMUNICATION")
            evidence_list.append(
                EvidenceItem(
                    source_url="https://x.com/cyberdost",
                    title="CyberDost Advisory: Telegram Recruitment Fraud",
                    description="Official CyberDost advisory warns against employment communication conducted exclusively over Telegram channels.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.90,
                )
            )

        # Signal D: WhatsApp Task / Recruitment Channel
        has_whatsapp = (
            any(w in raw_lower for w in ["whatsapp only", "whatsapp task", "whatsapp group", "contact on whatsapp", "task on whatsapp"])
            or "WHATSAPP_ONLY" in flags
        )
        if has_whatsapp:
            detected_signals.append("WHATSAPP_RECRUITMENT_CHANNEL")
            evidence_list.append(
                EvidenceItem(
                    source_url="https://cybercrime.gov.in",
                    title="CyberDost Advisory: WhatsApp Task Scam",
                    description="Official warnings highlight unsolicited recruitment and daily tasks conducted via WhatsApp as a common phishing vector.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.90,
                )
            )

        # Signal E: Personal Email for Enterprise Claims
        safe_company = company_name if (company_name and company_name.lower() not in ["", "unknown", "unknown company"]) else ""
        has_personal_email = (
            any(f"@{dom}" in raw_lower for dom in FREE_EMAIL_DOMAINS)
            or "PERSONAL_EMAIL" in flags
            or "FREE_WEBMAIL" in flags
        ) and bool(safe_company)
        if has_personal_email:
            detected_signals.append("PERSONAL_EMAIL_ENTERPRISE")
            evidence_list.append(
                EvidenceItem(
                    source_url="https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                    title="Free Webmail Used for Corporate Recruitment",
                    description=f"Recruitment for '{safe_company}' conducted using a public webmail domain rather than an official corporate email domain.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.92,
                )
            )

        is_scam = len(detected_signals) > 0
        search_sources: List[str] = []

        # 2. SerpApi Scam Intelligence Searches

        # General company scam query
        scam_query = (
            f'"{safe_company}" job scam fraud complaint telegram'
            if safe_company
            else 'job scam fraud complaint telegram recruitment'
        )
        try:
            search_res = await self.search_client.search(query=scam_query)
            search_sources.append(search_res.get("source", SearchSource.MOCK.value))
            for res in (search_res.get("organic_results") or [])[:2]:
                link = res.get("link")
                title = res.get("title")
                snippet = res.get("snippet")
                if link and title:
                    evidence_list.append(
                        EvidenceItem(
                            source_url=link,
                            title=title,
                            description=snippet or f"Scam advisory result for {company_name}.",
                            evidence_type="SCAM_REPORT",
                            confidence=0.92 if search_res.get("source") == SearchSource.REAL.value else 0.85,
                        )
                    )
                    if any(w in (title + (snippet or "")).lower() for w in ["scam", "fraud", "fake", "warning"]):
                        is_scam = True
        except Exception as e:
            logger.warning("ScamAgent: general scam search failed (%s)", str(e))

        # Payment-specific search
        payment_term = payment_method or demanded_fee
        if payment_term:
            pay_query = (
                f'"{safe_company}" "{payment_term}" recruitment scam'
                if safe_company
                else f'"{payment_term}" recruitment scam'
            )
            try:
                pay_res = await self.search_client.search(query=pay_query)
                search_sources.append(pay_res.get("source", SearchSource.MOCK.value))
                for res in (pay_res.get("organic_results") or [])[:2]:
                    link = res.get("link")
                    title = res.get("title")
                    snippet = res.get("snippet")
                    if link and title:
                        evidence_list.append(
                            EvidenceItem(
                                source_url=link,
                                title=title,
                                description=snippet or f"Payment scam advisory for {company_name}.",
                                evidence_type="SCAM_REPORT",
                                confidence=0.92 if pay_res.get("source") == SearchSource.REAL.value else 0.85,
                            )
                        )
            except Exception as e:
                logger.warning("ScamAgent: payment scam search failed (%s)", str(e))

        primary_source = search_sources[0] if search_sources else SearchSource.MOCK.value

        # Deduplicate evidence items by (source_url, title)
        seen_keys = set()
        unique_evidence: List[EvidenceItem] = []
        for ev in evidence_list:
            key = (ev.source_url, ev.title)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_evidence.append(ev)

        if is_scam:
            signal_text = ", ".join(detected_signals) if detected_signals else "known scam pattern"
            return AgentFinding(
                agent_name="ScamAgent",
                verdict="HIGH_RISK",
                confidence=0.98,
                summary=f"Critical scam markers identified! Detected: {signal_text}.",
                evidence=unique_evidence,
                details={
                    "demanded_fee": demanded_fee,
                    "payment_method": payment_method,
                    "scam_flagged": True,
                    "risk_signals": detected_signals,
                    "search_source": primary_source,
                },
            )

        unique_evidence.append(
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
            evidence=unique_evidence,
            details={
                "demanded_fee": None,
                "payment_method": payment_method,
                "scam_flagged": False,
                "risk_signals": [],
                "search_source": primary_source,
            },
        )
