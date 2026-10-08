import {
  AssessedClaim,
  Claim,
  ClaimKind,
  ClaimStatus,
  EvidenceRelation,
  ExtractionStatus,
  OverallOutcome,
  RetrievalStatus,
  SourceKind,
  SourceTier,
} from '../types';

export const CLAIM_KIND_LABEL: Record<ClaimKind, string> = {
  employer: 'Employer',
  sender_email: 'Sender email',
  contact_phone: 'Contact phone',
  recruiter_name: 'Recruiter name',
  role: 'Role',
  location: 'Location',
  job_reference: 'Job reference',
  application_url: 'Application link',
  compensation: 'Compensation',
  payment_request: 'Payment request',
  credential_request: 'Credential request',
};

export const OUTCOME: Record<OverallOutcome, { label: string; tone: Tone; summary: string }> = {
  HIGH_RISK: {
    label: 'High risk',
    tone: 'rose',
    summary: 'The evidence shows strong scam signals. Do not pay, share credentials or sign anything.',
  },
  NEEDS_REVIEW: {
    label: 'Needs review',
    tone: 'amber',
    summary: 'Some claims conflict with public evidence or could not be checked. Confirm with the employer before acting.',
  },
  CANNOT_VERIFY: {
    label: 'Cannot verify',
    tone: 'slate',
    summary:
      'There was not enough independent evidence to check this offer. That is not proof of a scam — confirm it directly with the employer.',
  },
  NO_STRONG_RISK_SIGNALS: {
    label: 'No strong risk signals',
    tone: 'emerald',
    summary:
      'The checks found no strong warning signs. This does not confirm the offer is genuine — only the employer can do that.',
  },
};

export const CLAIM_STATUS: Record<ClaimStatus, { label: string; tone: Tone }> = {
  SUPPORTED: { label: 'Supported', tone: 'emerald' },
  CONTRADICTED: { label: 'Contradicted', tone: 'rose' },
  UNRESOLVED: { label: 'Unresolved', tone: 'amber' },
  NOT_CHECKED: { label: 'Not checked', tone: 'slate' },
};

export const EXTRACTION_STATUS: Record<ExtractionStatus, string> = {
  EXTRACTED: 'Quoted from the offer',
  UNCERTAIN: 'Uncertain — please check',
  USER_CONFIRMED: 'Confirmed by you',
  USER_EDITED: 'Corrected by you',
  MISSING: 'Not found in the offer',
};

export const RELATION: Record<EvidenceRelation, { label: string; tone: Tone }> = {
  SUPPORTS: { label: 'Supports', tone: 'emerald' },
  CONTRADICTS: { label: 'Contradicts', tone: 'rose' },
  CONTEXT: { label: 'Context', tone: 'slate' },
};

export const SOURCE_KIND: Record<SourceKind, string> = {
  DOCUMENT: 'In the offer document',
  SEARCH_SNIPPET: 'Search result snippet',
  CHECKED_PAGE: 'Page checked',
};

export const SOURCE_TIER: Record<SourceTier, string> = {
  OFFICIAL_EMPLOYER: 'Official employer source',
  GOVERNMENT: 'Government source',
  ESTABLISHED_THIRD_PARTY: 'Established third party',
  USER_GENERATED: 'User-generated (forum/social)',
  OFFER_DOCUMENT: 'The offer itself',
  UNKNOWN: 'Unknown source',
};

export const RETRIEVAL: Record<RetrievalStatus, string> = {
  LIVE: 'Live search',
  CACHED: 'Cached search',
  DEMO: 'Demo data',
  FAILED: 'Retrieval failed',
};

export type Tone = 'rose' | 'amber' | 'slate' | 'emerald';

export const TONE_CLASSES: Record<Tone, { chip: string; border: string; text: string; soft: string }> = {
  rose: { chip: 'bg-rose-50 text-rose-700 border-rose-200', border: 'border-l-rose-500', text: 'text-rose-700', soft: 'bg-rose-50' },
  amber: { chip: 'bg-amber-50 text-amber-800 border-amber-200', border: 'border-l-amber-500', text: 'text-amber-800', soft: 'bg-amber-50' },
  slate: { chip: 'bg-slate-100 text-slate-700 border-slate-300', border: 'border-l-slate-400', text: 'text-slate-700', soft: 'bg-slate-50' },
  emerald: { chip: 'bg-emerald-50 text-emerald-700 border-emerald-200', border: 'border-l-emerald-500', text: 'text-emerald-700', soft: 'bg-emerald-50' },
};

export const formatTime = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '—');

// ---------------------------------------------------------------- plain-language status

export type PlainVerdict = 'red_flag' | 'good' | 'unconfirmed' | 'not_checked';

const DEMAND_KINDS: ClaimKind[] = ['payment_request', 'credential_request'];
export const isDemandKind = (kind: ClaimKind) => DEMAND_KINDS.includes(kind);

/**
 * What a claim's status means for the reader: good sign, red flag, or unknown.
 * Contract statuses say whether a claim is *true*; for a payment demand,
 * "supported" means the demand really is in the offer, which is a red flag.
 */
export function plainStatus(claim: Claim, assessment?: AssessedClaim): { verdict: PlainVerdict; label: string; tone: Tone } {
  const status = assessment?.status ?? 'NOT_CHECKED';
  if (isDemandKind(claim.kind)) {
    if (!claim.value) return { verdict: 'good', label: 'None in the offer', tone: 'emerald' };
    if (status === 'SUPPORTED') return { verdict: 'red_flag', label: 'Red flag · found in offer', tone: 'rose' };
    return { verdict: 'not_checked', label: 'Not checked', tone: 'slate' };
  }
  if (!claim.value) return { verdict: 'not_checked', label: 'Not in the offer', tone: 'slate' };
  switch (status) {
    case 'SUPPORTED':
      return { verdict: 'good', label: 'Confirmed', tone: 'emerald' };
    case 'CONTRADICTED':
      return { verdict: 'red_flag', label: "Red flag · doesn't match", tone: 'rose' };
    case 'UNRESOLVED':
      return { verdict: 'unconfirmed', label: "Couldn't confirm", tone: 'amber' };
    default:
      return { verdict: 'not_checked', label: 'Not checked', tone: 'slate' };
  }
}

/** Everyday wording for the most common assessment reasons; falls back to the backend's own explanation. */
export function plainExplanation(claim: Claim, assessment?: AssessedClaim): string | null {
  if (!assessment) return null;
  const codes = assessment.reason_codes;
  const has = (code: string) => codes.includes(code);
  if (claim.kind === 'payment_request' && has('UPFRONT_PAYMENT_DEMAND'))
    return 'This offer asks you to pay money. Genuine employers never charge candidates — this is the most common job scam.';
  if (claim.kind === 'credential_request' && has('CREDENTIAL_THEFT_DEMAND'))
    return 'This offer asks for passwords, OTPs or bank details. No real employer needs these to hire you.';
  if (has('SENDER_DOMAIN_MISMATCH')) return assessment.explanation;
  if (has('OFFICIAL_DOMAIN_RESOLVED'))
    return 'This company really exists — we found its official website. That alone does not prove this offer came from it.';
  if (has('PUBLIC_LISTING_MATCH'))
    return 'The company itself publishes this contact on its own website.';
  if (has('NO_PUBLIC_LISTING_FOUND'))
    return 'We did not find this contact published by the company. Not a scam sign by itself.';
  if (has('OFFICIAL_DOMAIN_UNRESOLVED'))
    return 'We could not find an official website for this company. Small or new companies can be hard to find.';
  if (has('VACANCY_NOT_FOUND') || has('NO_MATCHING_VACANCY'))
    return 'We did not find this job listed publicly. Many real jobs are never listed, so this is not a scam sign by itself.';
  if (codes.some((c) => c.startsWith('LOCATION_')))
    return 'We could not confirm this job location from public hiring records.';
  if (has('NO_SALARY_BENCHMARK'))
    return 'We could not find reliable public salary data for this exact role and pay.';
  if (has('SEARCH_UNAVAILABLE'))
    return 'The search for this did not finish. Running the investigation again may help.';
  if (has('CHECK_NOT_EXECUTED'))
    return 'This was not checked in this run (time or search limit reached).';
  return assessment.explanation;
}
