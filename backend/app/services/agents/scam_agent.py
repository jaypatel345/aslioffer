from typing import Optional, List, Dict, Any
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient, SearchSource, SearchResult
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
        logger.info("ScamAgent investigation started")

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
                    source_url="document://submitted-offer",
                    title="Advance Fee / Security Deposit Scam Warning",
                    description="The submitted document contains an upfront fee or deposit indicator; confirm the request independently.",
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
                    source_url="document://submitted-offer",
                    title="Direct UPI Payment Request Flag",
                    description="The submitted document contains a recruitment payment-channel indicator.",
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
                    source_url="document://submitted-offer",
                    title="CyberDost Advisory: Telegram Recruitment Fraud",
                    description="Telegram communication is mentioned in the submitted document; context requires review.",
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
                    source_url="document://submitted-offer",
                    title="CyberDost Advisory: WhatsApp Task Scam",
                    description="The submitted document contains a WhatsApp recruitment-channel indicator.",
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
                    source_url="document://submitted-offer",
                    title="Free Webmail Used for Corporate Recruitment",
                    description=f"Recruitment for '{safe_company}' conducted using a public webmail domain rather than an official corporate email domain.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.92,
                )
            )

        is_scam = len(detected_signals) > 0
        provider_failed = False
        search_sources: List[str] = []
        checks = {}

        def record(name, result):
            nonlocal provider_failed
            if not result.is_live:
                provider_failed = True
            checks[name] = {
                "provider_status": "SUCCESS" if result.is_live else "FAILED",
                "search_status": result.outcome.value if result.is_live or result.get("source") == "FAILED" else "DEMO",
                "search_source": result.get("source"),
                "error": result.error or ("Live search evidence unavailable" if not result.is_live else None),
            }

        # 2. SerpApi Scam Intelligence Searches

        # General company scam query
        scam_query = (
            f'"{safe_company}" job scam fraud complaint telegram'
            if safe_company
            else 'job scam fraud complaint telegram recruitment'
        )
        try:
            raw_res = await self.search_client.search(query=scam_query)
            search_res = SearchResult.from_dict_or_result(raw_res, query=scam_query)
            search_sources.append(search_res.get("source", SearchSource.FAILED.value))
            record("company_reports", search_res)
            if not search_res.is_live:
                provider_failed = True
            else:
                for res in (search_res.organic_results or [])[:2]:
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
        except Exception:
            provider_failed = True
            checks["company_reports"] = {"provider_status": "FAILED", "search_status": "PROVIDER_FAILURE", "error": "Search integration failed"}
            logger.warning("ScamAgent: general scam search failed")

        # Payment-specific search
        payment_term = payment_method or demanded_fee
        if payment_term:
            pay_query = (
                f'"{safe_company}" "{payment_term}" recruitment scam'
                if safe_company
                else f'"{payment_term}" recruitment scam'
            )
            try:
                raw_pay = await self.search_client.search(query=pay_query)
                pay_res = SearchResult.from_dict_or_result(raw_pay, query=pay_query)
                search_sources.append(pay_res.get("source", SearchSource.FAILED.value))
                record("payment_reports", pay_res)
                if not pay_res.is_live:
                    provider_failed = True
                else:
                    for res in (pay_res.organic_results or [])[:2]:
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
            except Exception:
                provider_failed = True
                checks["payment_reports"] = {"provider_status": "FAILED", "search_status": "PROVIDER_FAILURE", "error": "Search integration failed"}
                logger.warning("ScamAgent: payment scam search failed")

        primary_source = search_sources[0] if search_sources else (SearchSource.FAILED.value if provider_failed else SearchSource.REAL.value)

        failed = [check for check in checks.values() if check["provider_status"] == "FAILED"]
        provider_status = "PARTIAL" if failed and len(failed) < len(checks) else "FAILED" if failed else "SUCCESS"
        search_status = "PARTIAL" if provider_status == "PARTIAL" else failed[0]["search_status"] if failed else (
            "SUCCESSFUL_EMPTY" if checks and all(c["search_status"] == "ZERO_RESULTS" for c in checks.values()) else "SUCCESS")

        # Deduplicate evidence items by (source_url, title)
        seen_keys = set()
        unique_evidence: List[EvidenceItem] = []
        for ev in evidence_list:
            key = (ev.source_url, ev.title)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_evidence.append(ev)

        # Never erase explicit scam indicators present in the submitted offer just because external searches fail
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
                    "provider_status": provider_status,
                    "search_status": search_status,
                    "checks": checks,
                    "error": failed[0]["error"] if failed else None,
                    "local_scan_completed": True,
                },
            )

        return AgentFinding(
            agent_name="ScamAgent",
            verdict="CANNOT_VERIFY" if provider_failed else "VERIFIED",
            confidence=0.0 if provider_failed else 0.90,
            summary="No local scam indicators detected; external checks were unavailable or incomplete."
                if provider_failed else "No local scam indicators detected; completed searches do not authenticate the offer.",
            evidence=unique_evidence,
            details={
                "demanded_fee": None,
                "payment_method": payment_method,
                "scam_flagged": False,
                "risk_signals": [],
                "search_source": primary_source,
                "provider_status": provider_status,
                "search_status": search_status,
                "checks": checks,
                "error": failed[0]["error"] if failed else None,
                "local_scan_completed": True,
            },
        )
