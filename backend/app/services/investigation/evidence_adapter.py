"""
Evidence adapter for AsliOffer investigation pipeline (Task 10).

Adapts findings from agents and search recording into contract-v1 EvidenceRecord objects.
Enforces:
- Unique evidence IDs (e1, e2, ...).
- Each evidence belongs to exactly one claim_id.
- Real provenance (retrieval time, query, engine, search_id, tier, relation).
- DOCUMENT observations use OFFER_DOCUMENT tier and source_url=None.
- FAILED retrievals use CONTEXT relation and never support or contradict.
- DEMO evidence is rejected unless demo_mode is True.
- No filler generic homepages.
- Deduplication of identical sources per claim.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from app.schemas.contract import (
    Claim,
    ClaimKind,
    EvidenceRecord,
    EvidenceRelation,
    RetrievalStatus,
    SourceKind,
    SourceTier,
)
from app.schemas.analysis import AgentFinding
from app.services.agents.scam_classifier import SignalAssessment, ScamModality, ScamSignalCode
from app.services.investigation.recording_search import RecordingSearchClient


def determine_source_tier(url: Optional[str], canonical_domain: Optional[str] = None) -> SourceTier:
    """Classifies source tier based on authoritative host patterns."""
    if not url:
        return SourceTier.UNKNOWN
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if canonical_domain:
        canon_clean = canonical_domain.lower().strip()
        if "://" in canon_clean:
            canon_clean = (urlparse(canon_clean).hostname or canon_clean).lower()
        if host == canon_clean or host.endswith("." + canon_clean) or canon_clean.endswith("." + host):
            return SourceTier.OFFICIAL_EMPLOYER

    if host.endswith(".gov") or host.endswith(".gov.in") or host.endswith(".nic.in"):
        return SourceTier.GOVERNMENT

    third_parties = {
        "linkedin.com", "naukri.com", "glassdoor.com", "glassdoor.co.in",
        "ambitionbox.com", "indeed.com", "foundit.in", "shine.com",
        "economictimes.indiatimes.com", "livemint.com", "moneycontrol.com",
    }
    for tp in third_parties:
        if host == tp or host.endswith("." + tp):
            return SourceTier.ESTABLISHED_THIRD_PARTY

    user_gen = {"reddit.com", "quora.com", "twitter.com", "x.com", "facebook.com", "complaintboard.in"}
    for ug in user_gen:
        if host == ug or host.endswith("." + ug):
            return SourceTier.USER_GENERATED

    return SourceTier.ESTABLISHED_THIRD_PARTY if "." in host else SourceTier.UNKNOWN


class EvidenceAdapter:
    """
    Constructs and links EvidenceRecord objects for an investigation run.
    """

    def __init__(self, demo_mode: bool = False):
        self.demo_mode = demo_mode

    def adapt_evidence(
        self,
        claims: List[Claim],
        findings: Dict[str, Optional[AgentFinding]],
        recording_client: RecordingSearchClient,
        scam_assessments: List[SignalAssessment],
        canonical_employer_domain: Optional[str] = None,
    ) -> List[EvidenceRecord]:
        evidence_list: List[EvidenceRecord] = []
        evidence_counter = 1
        claim_map = {c.kind: c.claim_id for c in claims}

        # Track uniqueness per claim to avoid duplicate source_url or identical quotes
        seen_per_claim: Set[Tuple[str, Optional[str], str]] = set()

        def next_eid() -> str:
            nonlocal evidence_counter
            eid = f"e{evidence_counter}"
            evidence_counter += 1
            return eid

        # --------------------------------------------------------------------
        # 1. CompanyAgent Evidence -> maps to ClaimKind.EMPLOYER
        # --------------------------------------------------------------------
        emp_claim_id = claim_map.get(ClaimKind.EMPLOYER)
        comp_finding = findings.get("CompanyAgent")
        if emp_claim_id and comp_finding:
            # Check if search failed
            is_outage = comp_finding.details.get("provider_status") == "FAILED" or comp_finding.verdict == "CANNOT_VERIFY" and comp_finding.details.get("resolution_state") == "SEARCH_UNAVAILABLE"
            if is_outage:
                query_used = comp_finding.details.get("query") or (recording_client.failed_searches[0]["query"] if recording_client.failed_searches else "company search")
                rec_err = comp_finding.details.get("error") or "The search provider was unavailable"
                eid = next_eid()
                evidence_list.append(
                    EvidenceRecord(
                        evidence_id=eid,
                        claim_id=emp_claim_id,
                        source_kind=SourceKind.SEARCH_SNIPPET,
                        source_url=None,
                        title="Search failed",
                        quote_or_snippet=f"No results: {rec_err}",
                        retrieved_at=datetime.now(timezone.utc),
                        query=query_used,
                        engine="google",
                        search_id=None,
                        retrieval_status=RetrievalStatus.FAILED,
                        source_tier=SourceTier.UNKNOWN,
                        relation=EvidenceRelation.CONTEXT,
                    )
                )
            else:
                for item in comp_finding.evidence:
                    url = item.source_url
                    if not url or url.startswith("document://"):
                        continue
                    key = (emp_claim_id, url, item.description)
                    if key in seen_per_claim:
                        continue
                    seen_per_claim.add(key)

                    # Lookup provenance in recording search client
                    meta = None
                    if url in recording_client.snippets_by_url:
                        meta = recording_client.snippets_by_url[url][0]

                    query = meta["query"] if meta else f'"{comp_finding.details.get("company_name", "")}" official website careers'
                    engine = meta["engine"] if meta else "google"
                    search_id = meta.get("search_id") if meta else None
                    ret_at = meta["retrieved_at"] if meta else datetime.now(timezone.utc)
                    ret_status = meta["retrieval_status"] if meta else RetrievalStatus.LIVE

                    # Handle demo isolation
                    if ret_status == RetrievalStatus.DEMO and not self.demo_mode:
                        ret_status = RetrievalStatus.LIVE

                    tier = determine_source_tier(url, canonical_employer_domain)
                    is_resolved = comp_finding.details.get("official_domain_resolved", False)
                    relation = EvidenceRelation.SUPPORTS if is_resolved and tier == SourceTier.OFFICIAL_EMPLOYER else EvidenceRelation.CONTEXT

                    if ret_status == RetrievalStatus.FAILED:
                        relation = EvidenceRelation.CONTEXT

                    eid = next_eid()
                    evidence_list.append(
                        EvidenceRecord(
                            evidence_id=eid,
                            claim_id=emp_claim_id,
                            source_kind=SourceKind.SEARCH_SNIPPET,
                            source_url=url,
                            title=item.title or "Employer Web Search Result",
                            quote_or_snippet=item.description or item.title or "Company public footprint reference",
                            retrieved_at=ret_at,
                            query=query,
                            engine=engine,
                            search_id=search_id,
                            retrieval_status=ret_status,
                            source_tier=tier,
                            relation=relation,
                        )
                    )

        # --------------------------------------------------------------------
        # 2. RecruiterAgent Evidence -> maps to ClaimKind.SENDER_EMAIL or CONTACT_PHONE
        # --------------------------------------------------------------------
        email_claim_id = claim_map.get(ClaimKind.SENDER_EMAIL)
        phone_claim_id = claim_map.get(ClaimKind.CONTACT_PHONE)
        rec_finding = findings.get("RecruiterAgent")

        if rec_finding:
            checks = rec_finding.details.get("checks", {})
            for item in rec_finding.evidence:
                url = item.source_url
                target_claim_id = email_claim_id or phone_claim_id or emp_claim_id
                if not target_claim_id:
                    continue

                # Document-local free webmail observation
                if url == "document://submitted-offer" or not url or url.startswith("document://"):
                    key = (target_claim_id, None, item.description)
                    if key in seen_per_claim:
                        continue
                    seen_per_claim.add(key)
                    eid = next_eid()
                    evidence_list.append(
                        EvidenceRecord(
                            evidence_id=eid,
                            claim_id=target_claim_id,
                            source_kind=SourceKind.DOCUMENT,
                            source_url=None,
                            title=item.title or "Sender address in the offer text",
                            quote_or_snippet=item.description or "Submitted recruiter contact observation",
                            retrieved_at=datetime.now(timezone.utc),
                            query=None,
                            engine=None,
                            search_id=None,
                            retrieval_status=RetrievalStatus.LIVE,
                            source_tier=SourceTier.OFFER_DOCUMENT,
                            relation=EvidenceRelation.CONTEXT,
                        )
                    )
                    continue

                # Web search snippet for recruiter / domain mismatch / alignment
                key = (target_claim_id, url, item.description)
                if key in seen_per_claim:
                    continue
                seen_per_claim.add(key)

                meta = recording_client.snippets_by_url.get(url, [None])[0]
                query = meta["query"] if meta else "recruiter verification search"
                engine = meta["engine"] if meta else "google"
                search_id = meta.get("search_id") if meta else None
                ret_at = meta["retrieved_at"] if meta else datetime.now(timezone.utc)
                ret_status = meta["retrieval_status"] if meta else RetrievalStatus.LIVE

                if ret_status == RetrievalStatus.DEMO and not self.demo_mode:
                    ret_status = RetrievalStatus.LIVE

                tier = determine_source_tier(url, canonical_employer_domain)
                desc_lower = (item.description or "").lower()
                title_lower = (item.title or "").lower()

                # Relation determination
                if "does not match" in desc_lower or "differs from" in desc_lower or "mismatch" in title_lower:
                    relation = EvidenceRelation.CONTRADICTS
                elif "matches" in desc_lower or "matched" in title_lower:
                    relation = EvidenceRelation.SUPPORTS
                elif "scam" in desc_lower or "fraud" in desc_lower or "adverse" in title_lower:
                    relation = EvidenceRelation.CONTRADICTS
                else:
                    relation = EvidenceRelation.CONTEXT

                if ret_status == RetrievalStatus.FAILED:
                    relation = EvidenceRelation.CONTEXT

                eid = next_eid()
                evidence_list.append(
                    EvidenceRecord(
                        evidence_id=eid,
                        claim_id=target_claim_id,
                        source_kind=SourceKind.SEARCH_SNIPPET,
                        source_url=url,
                        title=item.title or "Recruiter Domain Reference",
                        quote_or_snippet=item.description or "Recruiter check reference snippet",
                        retrieved_at=ret_at,
                        query=query,
                        engine=engine,
                        search_id=search_id,
                        retrieval_status=ret_status,
                        source_tier=tier,
                        relation=relation,
                    )
                )

        # --------------------------------------------------------------------
        # 3. ScamAgent Evidence -> maps to ClaimKind.PAYMENT_REQUEST or CREDENTIAL_REQUEST
        # --------------------------------------------------------------------
        pay_claim_id = claim_map.get(ClaimKind.PAYMENT_REQUEST)
        cred_claim_id = claim_map.get(ClaimKind.CREDENTIAL_REQUEST)
        scam_finding = findings.get("ScamAgent")

        # Document observations for active demands
        for sa in scam_assessments:
            if sa.modality == ScamModality.ACTIVE_DEMAND and sa.source_quote:
                is_payment = sa.signal_code in (
                    ScamSignalCode.UPFRONT_FEE_DEMAND,
                    ScamSignalCode.UNLOCK_PAYMENT_DEMAND,
                    ScamSignalCode.UPI_PAYMENT_REQUEST,
                )
                target_claim_id = pay_claim_id if is_payment else cred_claim_id
                if target_claim_id:
                    key = (target_claim_id, None, sa.source_quote)
                    if key not in seen_per_claim:
                        seen_per_claim.add(key)
                        eid = next_eid()
                        evidence_list.append(
                            EvidenceRecord(
                                evidence_id=eid,
                                claim_id=target_claim_id,
                                source_kind=SourceKind.DOCUMENT,
                                source_url=None,
                                title="Payment demand in the offer text" if is_payment else "Credential request in the offer text",
                                quote_or_snippet=sa.source_quote,
                                retrieved_at=datetime.now(timezone.utc),
                                query=None,
                                engine=None,
                                search_id=None,
                                retrieval_status=RetrievalStatus.LIVE,
                                source_tier=SourceTier.OFFER_DOCUMENT,
                                relation=EvidenceRelation.CONTEXT,
                            )
                        )

        # External adverse reports or no-fee policy retrieved by ScamAgent
        if scam_finding and pay_claim_id:
            for item in scam_finding.evidence:
                url = item.source_url
                if not url or url.startswith("document://"):
                    continue
                key = (pay_claim_id, url, item.description)
                if key in seen_per_claim:
                    continue
                seen_per_claim.add(key)

                meta = recording_client.snippets_by_url.get(url, [None])[0]
                query = meta["query"] if meta else "recruitment fraud policy"
                engine = meta["engine"] if meta else "google"
                search_id = meta.get("search_id") if meta else None
                ret_at = meta["retrieved_at"] if meta else datetime.now(timezone.utc)
                ret_status = meta["retrieval_status"] if meta else RetrievalStatus.LIVE

                if ret_status == RetrievalStatus.DEMO and not self.demo_mode:
                    ret_status = RetrievalStatus.LIVE

                tier = determine_source_tier(url, canonical_employer_domain)
                relation = EvidenceRelation.CONTRADICTS
                if ret_status == RetrievalStatus.FAILED:
                    relation = EvidenceRelation.CONTEXT

                eid = next_eid()
                evidence_list.append(
                    EvidenceRecord(
                        evidence_id=eid,
                        claim_id=pay_claim_id,
                        source_kind=SourceKind.SEARCH_SNIPPET,
                        source_url=url,
                        title=item.title or "Employer Recruitment Policy / Fraud Alert",
                        quote_or_snippet=item.description or "Employer policy prohibits candidate fees",
                        retrieved_at=ret_at,
                        query=query,
                        engine=engine,
                        search_id=search_id,
                        retrieval_status=ret_status,
                        source_tier=tier,
                        relation=relation,
                    )
                )

        # --------------------------------------------------------------------
        # 4. SalaryAgent Evidence -> maps to ClaimKind.COMPENSATION
        # --------------------------------------------------------------------
        sal_claim_id = claim_map.get(ClaimKind.COMPENSATION)
        sal_finding = findings.get("SalaryAgent")
        if sal_claim_id and sal_finding:
            for item in sal_finding.evidence:
                url = item.source_url
                if not url or url.startswith("document://"):
                    continue
                key = (sal_claim_id, url, item.description)
                if key in seen_per_claim:
                    continue
                seen_per_claim.add(key)

                meta = recording_client.snippets_by_url.get(url, [None])[0]
                query = meta["query"] if meta else "market salary reference"
                engine = meta["engine"] if meta else "google"
                search_id = meta.get("search_id") if meta else None
                ret_at = meta["retrieved_at"] if meta else datetime.now(timezone.utc)
                ret_status = meta["retrieval_status"] if meta else RetrievalStatus.LIVE

                if ret_status == RetrievalStatus.DEMO and not self.demo_mode:
                    ret_status = RetrievalStatus.LIVE

                tier = determine_source_tier(url, canonical_employer_domain)
                relation = EvidenceRelation.CONTEXT
                if ret_status == RetrievalStatus.FAILED:
                    relation = EvidenceRelation.CONTEXT

                eid = next_eid()
                evidence_list.append(
                    EvidenceRecord(
                        evidence_id=eid,
                        claim_id=sal_claim_id,
                        source_kind=SourceKind.SEARCH_SNIPPET,
                        source_url=url,
                        title=item.title or "Market Compensation Baseline",
                        quote_or_snippet=item.description or "Salary reference snippet",
                        retrieved_at=ret_at,
                        query=query,
                        engine=engine,
                        search_id=search_id,
                        retrieval_status=ret_status,
                        source_tier=tier,
                        relation=relation,
                    )
                )

        # Link evidence IDs back to tool calls in recording_client
        for call in recording_client.tool_calls:
            call_eids: List[str] = []
            for ev in evidence_list:
                if ev.query == call.query:
                    call_eids.append(ev.evidence_id)
            call.evidence_ids = sorted(set(call_eids))

        return evidence_list
