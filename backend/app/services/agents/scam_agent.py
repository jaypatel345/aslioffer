from typing import Optional, List, Dict, Any
from app.schemas.analysis import AgentFinding, EvidenceItem
from app.services.search.serpapi_client import SerpApiClient, SearchSource, SearchResult
from app.services.agents.scam_classifier import (
    ScamClassifier,
    ScamModality,
    ScamSignalCode,
    SignalAssessment,
    sanitize_and_redact_secrets,
)
from app.core.logging import logger

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com", "icloud.com"}


class ScamAgent:
    """
    Investigates direct scam indicators, such as demands for upfront fees (laptop security,
    training fee, onboarding deposit), UPI payment requests, Telegram/WhatsApp task groups,
    bank OTP/credential theft, unlock-earnings extortion, and live adverse reports.
    Uses contextual classification to distinguish actual demands from negated policies,
    quoted warnings, ordinary communication channels, and uncorroborated hints.
    """

    def __init__(self, search_client: Optional[SerpApiClient] = None):
        self.search_client = search_client or SerpApiClient()
        self.classifier = ScamClassifier()

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
        Evaluates context, localized negation, advisory quoting, and payment directions.
        """
        logger.info("ScamAgent investigation started")

        evidence_list: List[EvidenceItem] = []
        detected_signals: List[str] = []

        # 1. Contextual Signal Classification over document text and structured hints
        assessments: List[SignalAssessment] = self.classifier.classify(
            raw_text=raw_text,
            demanded_fee=demanded_fee,
            payment_method=payment_method,
            flags=flags,
        )

        active_demands = [a for a in assessments if a.modality == ScamModality.ACTIVE_DEMAND and a.contributes_to_verdict]
        ambiguous_signals = [a for a in assessments if a.modality == ScamModality.AMBIGUOUS and a.contributes_to_verdict]

        # Flags for fixture and consumer compatibility
        has_upfront_fee = any(a.signal_code == ScamSignalCode.UPFRONT_FEE_DEMAND for a in active_demands)
        has_unlock_earnings = any(a.signal_code == ScamSignalCode.UNLOCK_PAYMENT_DEMAND for a in active_demands)
        has_cred_theft = any(a.signal_code == ScamSignalCode.CREDENTIAL_THEFT_DEMAND for a in active_demands)
        has_upi = any(a.signal_code == ScamSignalCode.UPI_PAYMENT_REQUEST for a in active_demands)

        negated_fee_found = any(a.signal_code == ScamSignalCode.NEGATED_FEE_POLICY for a in assessments)
        quoted_warning_detected = any(a.signal_code == ScamSignalCode.QUOTED_SCAM_ADVISORY for a in assessments)
        telegram_present = any(a.signal_code == ScamSignalCode.TELEGRAM_COMMUNICATION for a in assessments)
        task_scam_detected = has_unlock_earnings or any(
            a.signal_code == ScamSignalCode.WHATSAPP_RECRUITMENT_CHANNEL and "task" in (a.source_quote or "").lower()
            for a in assessments
        )
        otp_requested = has_cred_theft
        password_requested = has_cred_theft

        # Build grounded local evidence items for active demands
        if has_upfront_fee:
            detected_signals.append(ScamSignalCode.UPFRONT_FEE_DEMAND)
            fee_desc = demanded_fee or "mandatory upfront fee / security deposit"
            evidence_list.append(
                EvidenceItem(
                    source_url="document://submitted-offer",
                    title="Advance Fee / Security Deposit Demand in Submitted Document",
                    description=f"The submitted document contains a mandatory upfront fee or deposit indicator ({fee_desc}).",
                    evidence_type="SCAM_REPORT",
                    confidence=0.99,
                )
            )

        if has_unlock_earnings:
            detected_signals.append(ScamSignalCode.UNLOCK_PAYMENT_DEMAND)
            evidence_list.append(
                EvidenceItem(
                    source_url="document://submitted-offer",
                    title="Payment to Unlock Earnings Demand in Submitted Document",
                    description="The submitted document requires a payment or release charge to unlock task earnings or job wages.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.99,
                )
            )

        if has_cred_theft:
            detected_signals.append(ScamSignalCode.CREDENTIAL_THEFT_DEMAND)
            evidence_list.append(
                EvidenceItem(
                    source_url="document://submitted-offer",
                    title="Bank OTP / Credential Theft Demand in Submitted Document",
                    description="The submitted document solicits candidate bank OTPs, passwords, or account-access secrets.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.99,
                )
            )

        if has_upi:
            detected_signals.append(ScamSignalCode.UPI_PAYMENT_REQUEST)
            method_desc = payment_method or "UPI / Mobile Wallet"
            evidence_list.append(
                EvidenceItem(
                    source_url="document://submitted-offer",
                    title="Direct UPI Payment Request in Submitted Document",
                    description=f"The submitted document directs the candidate to remit funds via {method_desc}.",
                    evidence_type="SCAM_REPORT",
                    confidence=0.98,
                )
            )

        safe_company = company_name if (company_name and company_name.lower() not in ["", "unknown", "unknown company"]) else ""

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
                        text_content = f"{title} {snippet or ''}".lower()
                        is_relevant = bool(safe_company and safe_company.lower() in text_content)
                        is_generic = any(g in text_content for g in ["tips to avoid", "safety guidelines", "how to identify"])
                        # Distinguish general prevention advice from attributable adverse reports
                        if is_relevant or not is_generic:
                            evidence_list.append(
                                EvidenceItem(
                                    source_url=link,
                                    title=title,
                                    description=snippet or f"Scam advisory result for {company_name}.",
                                    evidence_type="SCAM_REPORT",
                                    confidence=0.92 if (search_res.get("source") == SearchSource.REAL.value and is_relevant) else 0.85,
                                )
                            )
        except Exception:
            provider_failed = True
            checks["company_reports"] = {"provider_status": "FAILED", "search_status": "PROVIDER_FAILURE", "error": "Search integration failed"}
            logger.warning("ScamAgent: general scam search failed")

        payment_term = payment_method or demanded_fee
        if payment_term and has_upfront_fee:
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

        # 3. Verdict Determination & Decision Matrix

        # Branch A: Active demands for advance fees, unlock payments, or credential theft
        if active_demands:
            if has_cred_theft:
                summary = "Critical threat: Explicit solicitation of bank OTP and account passwords represents direct credential theft and banking fraud."
                reason_code = "CREDENTIAL_THEFT_DETECTED"
            elif has_unlock_earnings:
                summary = "Advance payment required to release earned funds or unlock job tasks is a classic task-scam extortion pattern."
                reason_code = "UNLOCK_PAYMENT_DETECTED"
            elif has_upfront_fee:
                summary = "Direct demand for advance security deposit via UPI violates Ministry of Labour guidelines and constitutes advance fee fraud." if has_upi else "Direct demand for advance security deposit or upfront recruitment fee violates employment guidelines and constitutes advance fee fraud."
                reason_code = "ADVANCE_FEE_DETECTED"
            else:
                summary = f"Critical scam markers identified! Detected: {', '.join(detected_signals)}."
                reason_code = "ADVANCE_FEE_DETECTED"

            return AgentFinding(
                agent_name="ScamAgent",
                verdict="HIGH_RISK",
                confidence=0.98,
                summary=summary,
                evidence=unique_evidence,
                details={
                    "demanded_fee": demanded_fee,
                    "payment_method": payment_method,
                    "scam_flagged": True,
                    "risk_signals": detected_signals,
                    "signal_assessments": [a.to_dict() for a in assessments],
                    "fee_detected": (has_upfront_fee or has_unlock_earnings),
                    "fee_amount": demanded_fee,
                    "negated_fee_found": negated_fee_found,
                    "quoted_warning_detected": quoted_warning_detected,
                    "telegram_present": telegram_present,
                    "task_scam_detected": task_scam_detected,
                    "otp_requested": otp_requested,
                    "password_requested": password_requested,
                    "unlock_earnings_detected": has_unlock_earnings,
                    "reason_code": reason_code,
                    "search_source": primary_source,
                    "provider_status": provider_status,
                    "search_status": search_status,
                    "checks": checks,
                    "error": failed[0]["error"] if failed else None,
                    "local_scan_completed": True,
                },
            )

        # Branch B: Ambiguous requests, uncorroborated structured hints, or ordinary Telegram cautions
        if ambiguous_signals:
            if telegram_present and not active_demands:
                summary = "Telegram channel mentioned for announcements without payment requests or task scam patterns; treated as caution, not definitive fraud."
                reason_code = "TELEGRAM_UNVERIFIED_CHANNEL"
            else:
                summary = "Ambiguous payment channel or uncorroborated fee terms require manual review."
                reason_code = "SUSPICIOUS_PAYMENT_CHANNEL_OR_TERMS"

            return AgentFinding(
                agent_name="ScamAgent",
                verdict="NEEDS_REVIEW",
                confidence=0.70,
                summary=summary,
                evidence=unique_evidence,
                details={
                    "demanded_fee": demanded_fee,
                    "payment_method": payment_method,
                    "scam_flagged": False,
                    "risk_signals": [],
                    "signal_assessments": [a.to_dict() for a in assessments],
                    "fee_detected": False,
                    "negated_fee_found": negated_fee_found,
                    "quoted_warning_detected": quoted_warning_detected,
                    "telegram_present": telegram_present,
                    "task_scam_detected": task_scam_detected,
                    "otp_requested": False,
                    "password_requested": False,
                    "unlock_earnings_detected": False,
                    "reason_code": reason_code,
                    "search_source": primary_source,
                    "provider_status": provider_status,
                    "search_status": search_status,
                    "checks": checks,
                    "error": failed[0]["error"] if failed else None,
                    "local_scan_completed": True,
                },
            )

        # Branch C: Clean local assessment, but external search provider failed / outage
        if provider_failed:
            return AgentFinding(
                agent_name="ScamAgent",
                verdict="CANNOT_VERIFY",
                confidence=0.0,
                summary="No local scam indicators detected; external checks were unavailable or incomplete.",
                evidence=unique_evidence,
                details={
                    "demanded_fee": None,
                    "payment_method": payment_method,
                    "scam_flagged": False,
                    "risk_signals": [],
                    "signal_assessments": [a.to_dict() for a in assessments],
                    "fee_detected": False,
                    "negated_fee_found": negated_fee_found,
                    "quoted_warning_detected": quoted_warning_detected,
                    "telegram_present": telegram_present,
                    "task_scam_detected": False,
                    "otp_requested": False,
                    "password_requested": False,
                    "unlock_earnings_detected": False,
                    "search_source": primary_source,
                    "provider_status": provider_status,
                    "search_status": search_status,
                    "checks": checks,
                    "error": failed[0]["error"] if failed else None,
                    "local_scan_completed": True,
                },
            )

        # Branch D: Clean offer with completed searches
        if negated_fee_found:
            summary = "Disclaimer stating company never charges security deposits recognized as anti-fraud policy, not a payment demand."
        elif quoted_warning_detected:
            summary = "Mention of fee language is inside an anti-scam advisory cautioning against third-party fraud, not an offer demand."
        else:
            summary = "No local scam indicators detected; completed searches do not authenticate the offer."

        return AgentFinding(
            agent_name="ScamAgent",
            verdict="VERIFIED",
            confidence=0.90,
            summary=summary,
            evidence=unique_evidence,
            details={
                "demanded_fee": None,
                "payment_method": payment_method,
                "scam_flagged": False,
                "risk_signals": [],
                "signal_assessments": [a.to_dict() for a in assessments],
                "fee_detected": False,
                "negated_fee_found": negated_fee_found,
                "quoted_warning_detected": quoted_warning_detected,
                "telegram_present": False,
                "task_scam_detected": False,
                "otp_requested": False,
                "password_requested": False,
                "unlock_earnings_detected": False,
                "search_source": primary_source,
                "provider_status": provider_status,
                "search_status": search_status,
                "checks": checks,
                "error": failed[0]["error"] if failed else None,
                "local_scan_completed": True,
            },
        )
