"""Claim-specific evidence adaptation. Missing provenance never becomes live evidence."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.schemas.contract import (ClaimKind, EvidenceRecord, EvidenceRelation, RetrievalStatus,
                                 SourceKind, SourceTier)
from app.services.agents.scam_classifier import ScamModality, ScamSignalCode, sanitize_and_redact_secrets
from app.services.risk.assessment_engine import canonicalize_url
from app.services.search.domain_resolver import DomainResolver


def determine_source_tier(url: Optional[str], canonical_domain: Optional[str] = None) -> SourceTier:
    host = (urlparse(url or '').hostname or '').lower()
    canon = (urlparse(canonical_domain).hostname if canonical_domain and '://' in canonical_domain else canonical_domain or '').lower()
    if canon.startswith('www.'):
        canon = canon[4:]
    if host and canon and (host == canon or host.endswith('.' + canon)):
        return SourceTier.OFFICIAL_EMPLOYER
    if host.endswith(('.gov', '.gov.in', '.nic.in')):
        return SourceTier.GOVERNMENT
    # Hosted ATS platforms are established third parties, never labeled OFFICIAL_EMPLOYER
    if DomainResolver.is_hosted_careers_platform(host):
        return SourceTier.ESTABLISHED_THIRD_PARTY
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
                       canonical_employer_domain=None, corroboration_result=None):
        records: List[EvidenceRecord] = []
        seen = set()
        by_kind = {c.kind: c for c in claims}

        def add(claim, meta=None, quote=None, title='', relation=EvidenceRelation.CONTEXT):
            if not claim or not claim.value:
                return
            if meta and meta.get('retrieval_status') == RetrievalStatus.DEMO and not self.demo_mode:
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
            record = EvidenceRecord(
                evidence_id=f'e{len(records)+1}',
                claim_id=claim.claim_id,
                source_kind=SourceKind.SEARCH_SNIPPET if meta else SourceKind.DOCUMENT,
                source_url=url,
                title=title,
                quote_or_snippet=quote,
                retrieved_at=meta['retrieved_at'] if meta else datetime.now(timezone.utc),
                query=meta.get('query') if meta else None,
                engine=meta.get('engine') if meta else None,
                search_id=meta.get('search_id') if meta else None,
                retrieval_status=meta.get('retrieval_status') if meta else RetrievalStatus.LIVE,
                source_tier=determine_source_tier(url, canonical_employer_domain) if meta else SourceTier.OFFER_DOCUMENT,
                relation=relation,
            )
            records.append(record)
            if meta:
                call = meta.get('call')
                if call is not None and record.evidence_id not in call.evidence_ids:
                    call.evidence_ids.append(record.evidence_id)

        def provenance(url, step):
            return [m for key, entries in recording_client.snippets_by_url.items()
                    if canonicalize_url(key) == canonicalize_url(url)
                    for m in entries if m.get('step') == step
                    or (step == 'resolve_employer_domain' and m.get('step') == 'adaptive_employer_context')
                    or (step == 'check_recruiter_contact' and m.get('step') in ('resolve_employer_domain', 'adaptive_employer_context', 'adaptive_agency_authorization', 'adaptive_recruiter_affiliation'))
                    or (step == 'check_scam_signals' and m.get('step') in ('adaptive_recruitment_fee_policy', 'check_scam_signals'))
                    or (step in ('corroborate_job_role', 'corroborate_job_reference', 'discover_confirmation_contact') or m.get('step') in ('adaptive_job_role_corroboration', 'adaptive_job_reference_corroboration', 'adaptive_confirmation_route_discovery'))]

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
                    if by_kind.get(ClaimKind.PAYMENT_REQUEST) and by_kind.get(ClaimKind.PAYMENT_REQUEST).value:
                        add(by_kind.get(ClaimKind.PAYMENT_REQUEST), meta, relation=EvidenceRelation.CONTEXT)
                    add(by_kind.get(ClaimKind.EMPLOYER), meta)

        salary = findings.get('SalaryAgent')
        if salary:
            for item in salary.evidence:
                for meta in provenance(item.source_url, 'check_compensation_benchmark'):
                    add(by_kind.get(ClaimKind.COMPENSATION), meta)

        # Adapt Corroboration Observations (Task 12)
        if corroboration_result and corroboration_result.observations:
            for claim_id, obs in corroboration_result.observations.items():
                claim = next((c for c in claims if c.claim_id == claim_id), None)
                if not claim or not claim.value:
                    continue
                for ev_item in obs.evidence_items:
                    if isinstance(ev_item, dict):
                        url = ev_item.get("source_url")
                        title = ev_item.get("title")
                        desc = ev_item.get("description", "")
                        rel = ev_item.get("relation")
                    else:
                        url = getattr(ev_item, "source_url", None)
                        title = getattr(ev_item, "title", None)
                        desc = getattr(ev_item, "description", "")
                        rel = getattr(ev_item, "relation", None)

                    if rel is None:
                        if obs.status == ClaimStatus.SUPPORTED:
                            rel = EvidenceRelation.SUPPORTS
                        elif obs.status == ClaimStatus.CONTRADICTED:
                            rel = EvidenceRelation.CONTRADICTS
                        else:
                            rel = EvidenceRelation.CONTEXT

                    matching_metas = [
                        m for key, entries in recording_client.snippets_by_url.items()
                        if canonicalize_url(key) == canonicalize_url(url)
                        for m in entries
                    ] if url else []
                    if matching_metas:
                        for meta in matching_metas:
                            add(claim, meta=meta, title=title, quote=desc, relation=rel)
                    else:
                        item_title = title or "Hiring record observation"
                        add(claim, quote=desc, title=item_title, relation=rel)

        # Resolve confirmation route evidence ID to actual EvidenceRecord
        if corroboration_result and corroboration_result.confirmation_route:
            ev_target = corroboration_result.confirmation_route.evidence_id
            matching_rec = next(
                (r for r in records if r.source_url and canonicalize_url(r.source_url) == canonicalize_url(ev_target)),
                None,
            )
            if not matching_rec and ev_target:
                # Check if ev_target was recorded in snippets_by_url
                for key, entries in recording_client.snippets_by_url.items():
                    if canonicalize_url(key) == canonicalize_url(ev_target):
                        for m in entries:
                            emp_claim = by_kind.get(ClaimKind.EMPLOYER)
                            if emp_claim:
                                add(emp_claim, meta=m, relation=EvidenceRelation.CONTEXT)
                        break
                matching_rec = next(
                    (r for r in records if r.source_url and canonicalize_url(r.source_url) == canonicalize_url(ev_target)),
                    None,
                )

            if matching_rec and (matching_rec.retrieval_status != RetrievalStatus.DEMO or self.demo_mode) and matching_rec.retrieval_status != RetrievalStatus.FAILED:
                corroboration_result.confirmation_route.evidence_id = matching_rec.evidence_id
            else:
                corroboration_result.confirmation_route = None

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
