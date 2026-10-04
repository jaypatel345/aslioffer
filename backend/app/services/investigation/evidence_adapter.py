"""Claim-specific evidence adaptation. Missing provenance never becomes live evidence."""
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from app.schemas.contract import (ClaimKind, EvidenceRecord, EvidenceRelation, RetrievalStatus,
                                 SourceKind, SourceTier)
from app.services.agents.scam_classifier import ScamModality, ScamSignalCode, sanitize_and_redact_secrets
from app.services.risk.assessment_engine import canonicalize_url


def determine_source_tier(url: Optional[str], canonical_domain: Optional[str] = None) -> SourceTier:
    host = (urlparse(url or '').hostname or '').lower()
    canon = (urlparse(canonical_domain).hostname if canonical_domain and '://' in canonical_domain else canonical_domain or '').lower()
    if canon.startswith('www.'):
        canon = canon[4:]
    if host and canon and (host == canon or host.endswith('.' + canon)):
        return SourceTier.OFFICIAL_EMPLOYER
    if host.endswith(('.gov', '.gov.in', '.nic.in')):
        return SourceTier.GOVERNMENT
    for domain in ('linkedin.com', 'naukri.com', 'glassdoor.com', 'glassdoor.co.in', 'ambitionbox.com',
                   'indeed.com', 'foundit.in', 'shine.com', 'economictimes.indiatimes.com', 'livemint.com', 'moneycontrol.com'):
        if host == domain or host.endswith('.' + domain):
            return SourceTier.ESTABLISHED_THIRD_PARTY
    for domain in ('reddit.com', 'quora.com', 'twitter.com', 'x.com', 'facebook.com', 'complaintboard.in'):
        if host == domain or host.endswith('.' + domain):
            return SourceTier.USER_GENERATED
    return SourceTier.UNKNOWN


class EvidenceAdapter:
    def __init__(self, demo_mode=False):
        self.demo_mode = demo_mode

    def adapt_evidence(self, claims, findings, recording_client, scam_assessments,
                       canonical_employer_domain=None):
        records = []
        seen = set()
        by_kind = {c.kind: c for c in claims}

        def add(claim, meta=None, quote=None, title='', relation=EvidenceRelation.CONTEXT):
            if not claim or not claim.value:
                return
            if meta and meta['retrieval_status'] == RetrievalStatus.DEMO and not self.demo_mode:
                return
            url = meta['source_url'] if meta else None
            if url and (urlparse(url).scheme not in ('http', 'https') or urlparse(url).username
                        or 'api_key=' in url.lower()):
                return
            quote = sanitize_and_redact_secrets(quote if quote is not None else meta['snippet'])
            title = sanitize_and_redact_secrets(title or (meta['title'] if meta else 'Document observation'))
            key = (claim.claim_id, canonicalize_url(url) if url else None, title, quote)
            if key in seen:
                return
            seen.add(key)
            record = EvidenceRecord(evidence_id=f'e{len(records)+1}', claim_id=claim.claim_id,
                source_kind=SourceKind.SEARCH_SNIPPET if meta else SourceKind.DOCUMENT,
                source_url=url, title=title, quote_or_snippet=quote,
                retrieved_at=meta['retrieved_at'] if meta else datetime.now(timezone.utc),
                query=meta['query'] if meta else None, engine=meta['engine'] if meta else None,
                search_id=meta.get('search_id') if meta else None,
                retrieval_status=meta['retrieval_status'] if meta else RetrievalStatus.LIVE,
                source_tier=determine_source_tier(url, canonical_employer_domain) if meta else SourceTier.OFFER_DOCUMENT,
                relation=relation)
            records.append(record)
            if meta:
                call = meta.get('call')
                if call is not None and record.evidence_id not in call.evidence_ids:
                    call.evidence_ids.append(record.evidence_id)

        def provenance(url, step):
            return [m for key, entries in recording_client.snippets_by_url.items()
                    if canonicalize_url(key) == canonicalize_url(url)
                    for m in entries if m.get('step') == step or (step == 'check_recruiter_contact' and m.get('step') == 'resolve_employer_domain')]

        company = findings.get('CompanyAgent')
        if company:
            for item in company.evidence:
                for meta in provenance(item.source_url, 'resolve_employer_domain'):
                    tier = determine_source_tier(meta['source_url'], canonical_employer_domain)
                    relation = EvidenceRelation.SUPPORTS if company.details.get('official_domain_resolved') and tier == SourceTier.OFFICIAL_EMPLOYER else EvidenceRelation.CONTEXT
                    add(by_kind.get(ClaimKind.EMPLOYER), meta, relation=relation)

        recruiter = findings.get('RecruiterAgent')
        if recruiter:
            dimensions = recruiter.details.get('assessment_dimensions') or {}
            affiliation = dimensions.get('recruiter_affiliation') or {}
            affiliation_urls = affiliation.get('source_urls') or []
            strong_affiliation = affiliation.get('status') == 'SUPPORTED' and affiliation.get('evidence_strength') == 'strong_employer_published'
            for item in recruiter.evidence:
                for meta in provenance(item.source_url, 'check_recruiter_contact'):
                    text = (meta['title'] + ' ' + meta['snippet']).lower()
                    for kind in (ClaimKind.SENDER_EMAIL, ClaimKind.CONTACT_PHONE, ClaimKind.RECRUITER_NAME):
                        claim = by_kind.get(kind)
                        if not claim or not claim.value or claim.value.lower() not in text:
                            continue
                        # A claim is not contradicted by mere mention of "scam"
                        # or by the absence of a complaint.
                        relation = EvidenceRelation.CONTEXT
                        if strong_affiliation and item.source_url in affiliation_urls and determine_source_tier(item.source_url, canonical_employer_domain) == SourceTier.OFFICIAL_EMPLOYER:
                            relation = EvidenceRelation.SUPPORTS
                        add(claim, meta, relation=relation)

        payment_codes = (ScamSignalCode.UPFRONT_FEE_DEMAND, ScamSignalCode.UNLOCK_PAYMENT_DEMAND, ScamSignalCode.UPI_PAYMENT_REQUEST)
        for signal in scam_assessments:
            if signal.modality != ScamModality.ACTIVE_DEMAND or not signal.source_quote:
                continue
            if signal.signal_code in payment_codes:
                kind = ClaimKind.PAYMENT_REQUEST
            elif signal.signal_code == ScamSignalCode.CREDENTIAL_THEFT_DEMAND:
                kind = ClaimKind.CREDENTIAL_REQUEST
            else:
                continue
            claim = by_kind.get(kind)
            # A user-edited replacement must not inherit an old document demand.
            if claim and claim.source_quote and claim.source_quote == signal.source_quote:
                add(claim, quote=signal.source_quote, title='Demand in submitted document', relation=EvidenceRelation.SUPPORTS)

        scam = findings.get('ScamAgent')
        if scam:
            for item in scam.evidence:
                for meta in provenance(item.source_url, 'check_scam_signals'):
                    add(by_kind.get(ClaimKind.EMPLOYER), meta)

        salary = findings.get('SalaryAgent')
        if salary:
            for item in salary.evidence:
                for meta in provenance(item.source_url, 'check_compensation_benchmark'):
                    add(by_kind.get(ClaimKind.COMPENSATION), meta)
        # A failed search is retained as context with its recorded provenance.
        for failure in recording_client.failed_searches:
            kind = ClaimKind.EMPLOYER if failure['step'] == 'resolve_employer_domain' else ClaimKind.COMPENSATION if failure['step'] == 'check_compensation_benchmark' else None
            claim = by_kind.get(kind)
            if claim and claim.value:
                record = EvidenceRecord(evidence_id=f'e{len(records)+1}', claim_id=claim.claim_id,
                    source_kind=SourceKind.SEARCH_SNIPPET, source_url=None,
                    title='Retrieval unavailable', quote_or_snippet='No completed search result was obtained.',
                    retrieved_at=failure['retrieved_at'], query=failure['query'], engine=failure['engine'],
                    retrieval_status=RetrievalStatus.FAILED, source_tier=SourceTier.UNKNOWN,
                    relation=EvidenceRelation.CONTEXT)
                records.append(record)
                call = next((c for c in recording_client.tool_calls if c.query == failure['query']
                             and c.started_at == failure['retrieved_at']), None)
                if call:
                    call.evidence_ids.append(record.evidence_id)
        return records
