import {
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
