"""Conservative claim assessments without inventing executed corroboration."""
from app.schemas.contract import (AssessedClaim, ClaimKind, ClaimStatus, EvidenceRelation,
                                  ExtractionStatus, RetrievalStatus, SourceKind)
from app.services.investigation.claim_builder import is_redaction_placeholder


class ClaimAssessor:
    def assess_claims(self, claims, evidence_records, findings, scam_assessments,
                      canonical_employer_domain=None, provider_outage=False):
        assessed = []
        agents = {ClaimKind.EMPLOYER: 'CompanyAgent', ClaimKind.SENDER_EMAIL: 'RecruiterAgent',
                  ClaimKind.CONTACT_PHONE: 'RecruiterAgent', ClaimKind.RECRUITER_NAME: 'RecruiterAgent',
                  ClaimKind.COMPENSATION: 'SalaryAgent', ClaimKind.PAYMENT_REQUEST: 'ScamAgent',
                  ClaimKind.CREDENTIAL_REQUEST: 'ScamAgent'}
        for claim in claims:
            evidence = [e for e in evidence_records if e.claim_id == claim.claim_id]
            usable = [e for e in evidence if e.retrieval_status != RetrievalStatus.FAILED]
            relations = {e.relation for e in usable}
            ids = [e.evidence_id for e in evidence]
            agent = findings.get(agents.get(claim.kind))
            status = ClaimStatus.UNRESOLVED
            reason = 'No independent corroboration was established for this claim.'
            codes = ['NO_CORROBORATION']
            if claim.extraction_status == ExtractionStatus.MISSING or not claim.value:
                status, reason, codes = ClaimStatus.NOT_CHECKED, 'Required claim value is absent; no check was executed for it.', ['MISSING_INPUT']
                ids = []
            elif is_redaction_placeholder(claim.value):
                status, reason, codes = ClaimStatus.NOT_CHECKED, 'The identifier is redacted and was not searched.', ['REDACTED_IDENTIFIER']
                ids = []
            elif claim.extraction_status == ExtractionStatus.UNCERTAIN:
                status, reason, codes = ClaimStatus.NOT_CHECKED, 'Extraction is uncertain; confirm the claim before using it in searches.', ['EXTRACTION_UNCERTAIN']
                ids = []
            elif claim.kind in (ClaimKind.ROLE, ClaimKind.LOCATION, ClaimKind.JOB_REFERENCE, ClaimKind.APPLICATION_URL):
                status = ClaimStatus.NOT_CHECKED
                reason, codes = 'Independent corroboration for this claim is deferred; no targeted check was executed.', ['CORROBORATION_DEFERRED']
                ids = []
            elif claim.kind in (ClaimKind.PAYMENT_REQUEST, ClaimKind.CREDENTIAL_REQUEST):
                if any(e.source_kind == SourceKind.DOCUMENT and e.relation == EvidenceRelation.SUPPORTS for e in usable):
                    status = ClaimStatus.SUPPORTED
                    reason = 'The submitted document contains this demand. This supports the presence of the demand, not the legitimacy of the offer.'
                    codes = ['DOCUMENT_DEMAND_OBSERVED', 'UPFRONT_PAYMENT_DEMAND' if claim.kind == ClaimKind.PAYMENT_REQUEST else 'CREDENTIAL_THEFT_DEMAND']
                else:
                    status = ClaimStatus.NOT_CHECKED
                    reason, codes = 'No grounded document observation supports this supplied demand value.', ['NO_GROUNDED_DEMAND']
            elif agent is None:
                status, reason, codes = ClaimStatus.NOT_CHECKED, 'The relevant investigation check did not execute successfully.', ['CHECK_NOT_EXECUTED']
            elif agent.details.get('provider_status') == 'FAILED':
                reason, codes = 'The relevant external check was unavailable; no completed corroboration was obtained.', ['SEARCH_UNAVAILABLE']
            elif claim.kind == ClaimKind.COMPENSATION:
                # Existing salary snippets and fixed bands are context only.
                reason, codes = 'Retrieved context does not establish comparable pay data for this role and compensation period.', ['NO_SALARY_BENCHMARK']
            elif EvidenceRelation.CONTRADICTS in relations:
                status, reason, codes = ClaimStatus.CONTRADICTED, 'Attributable evidence contradicts the specific claim; offer authenticity remains unconfirmed.', ['CLAIM_CONTRADICTED']
            elif EvidenceRelation.SUPPORTS in relations:
                status = ClaimStatus.SUPPORTED
                if claim.kind == ClaimKind.EMPLOYER:
                    reason = 'Independent results support the employer public footprint; they do not authenticate this offer.'
                    codes = ['OFFICIAL_DOMAIN_RESOLVED']
                else:
                    reason = 'Employer-published evidence supports the claimed recruiter affiliation; it does not prove mailbox control, hiring authority, or offer issuance.'
                    codes = ['PUBLIC_LISTING_MATCH']
            else:
                reason = 'The completed check did not establish attributable corroboration. Empty results do not prove fraud or legitimacy.'
                codes = ['SPARSE_FOOTPRINT', 'OFFICIAL_DOMAIN_UNRESOLVED'] if claim.kind == ClaimKind.EMPLOYER else ['NO_PUBLIC_LISTING_FOUND']
            assessed.append(AssessedClaim(claim_id=claim.claim_id, status=status, explanation=reason,
                                         evidence_ids=ids, reason_codes=codes))
        return assessed
