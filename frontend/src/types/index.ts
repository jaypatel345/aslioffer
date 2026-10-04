// HTTP-layer shapes (backend/app/schemas/offer.py, schemas/runs.py). The
// investigation objects themselves are the contract-v1 types further down.

export interface Offer {
  id: number;
  title: string;
  source_type: string;
  raw_content: string;
  status: string;
  created_at: string;
}

export interface OfferUploadResponse {
  offer_id: number;
  title: string;
  status: string;
  message: string;
  /** Returned once; sent as X-Case-Token on every request for this case. */
  access_token: string;
  expires_at: string;
}

export interface RunRequest {
  offer_id: number;
  force_refresh?: boolean;
  confirmed_claims?: ConfirmedClaim[];
}

/** Locally extracted claims for the review step. Offsets refer to `text`. */
export interface ClaimPreview {
  case_id: number;
  text: string;
  claims: Claim[];
}

// ---------------------------------------------------------------------------
// API contract v1 — wire mirror of backend/app/schemas/contract.py.
// Spec and change rules: docs/api-contract.md. Example payloads that must keep
// type-checking against these types: docs/contract/v1/examples/*.json.
// Do not rename fields here without a contract update note and a sample payload.
// ---------------------------------------------------------------------------

export const CONTRACT_VERSION = '1.0.0';

export type OverallOutcome = 'HIGH_RISK' | 'NEEDS_REVIEW' | 'CANNOT_VERIFY' | 'NO_STRONG_RISK_SIGNALS';
/** Only the employer can confirm an offer, so this never leaves UNCONFIRMED. */
export type AuthenticityStatus = 'UNCONFIRMED';
export type SourceType = 'pdf' | 'screenshot' | 'email' | 'text';
export type ClaimKind =
  | 'employer'
  | 'sender_email'
  | 'contact_phone'
  | 'recruiter_name'
  | 'role'
  | 'location'
  | 'job_reference'
  | 'application_url'
  | 'compensation'
  | 'payment_request'
  | 'credential_request';
export type ExtractionStatus = 'EXTRACTED' | 'UNCERTAIN' | 'USER_CONFIRMED' | 'USER_EDITED' | 'MISSING';
export type SourceKind = 'DOCUMENT' | 'SEARCH_SNIPPET' | 'CHECKED_PAGE';
export type RetrievalStatus = 'LIVE' | 'CACHED' | 'DEMO' | 'FAILED';
export type SourceTier =
  | 'OFFICIAL_EMPLOYER'
  | 'GOVERNMENT'
  | 'ESTABLISHED_THIRD_PARTY'
  | 'USER_GENERATED'
  | 'OFFER_DOCUMENT'
  | 'UNKNOWN';
export type EvidenceRelation = 'SUPPORTS' | 'CONTRADICTS' | 'CONTEXT';
export type ClaimStatus = 'SUPPORTED' | 'CONTRADICTED' | 'UNRESOLVED' | 'NOT_CHECKED';
export type RunStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'PARTIAL' | 'FAILED';
export type EventStatus = 'STARTED' | 'COMPLETED' | 'SKIPPED' | 'FAILED';

export interface ConfirmedClaim {
  claim_id: string;
  kind: ClaimKind;
  value: string;
  extraction_status: 'USER_CONFIRMED' | 'USER_EDITED';
}

export interface CaseInput {
  contract_version: string;
  case_id: number;
  run_id: string;
  source_type: SourceType;
  redacted_text: string;
  confirmed_claims: ConfirmedClaim[];
  demo_mode: boolean;
}

export interface Claim {
  claim_id: string;
  kind: ClaimKind;
  value: string | null;
  /** Exact span from the document; null for MISSING or USER_EDITED values. */
  source_quote: string | null;
  start_offset: number | null;
  end_offset: number | null;
  page: number | null;
  extraction_status: ExtractionStatus;
}

export interface EvidenceRecord {
  evidence_id: string;
  claim_id: string;
  source_kind: SourceKind;
  /** Null for observations inside the offer document itself. */
  source_url: string | null;
  title: string;
  quote_or_snippet: string;
  retrieved_at: string;
  query: string | null;
  engine: string | null;
  search_id: string | null;
  retrieval_status: RetrievalStatus;
  source_tier: SourceTier;
  relation: EvidenceRelation;
}

export interface AssessedClaim {
  claim_id: string;
  status: ClaimStatus;
  explanation: string;
  evidence_ids: string[];
  reason_codes: string[];
}

/** Completeness of the investigation — never display this as a fraud probability. */
export interface Coverage {
  checked_claims: number;
  total_claims: number;
  unresolved_claims: number;
  failed_checks: number;
}

export interface ConfirmationRoute {
  channel: string;
  destination: string;
  evidence_id: string;
  draft_message: string | null;
}

export interface ToolCall {
  step: string;
  tool: string;
  query: string | null;
  reason: string;
  status: EventStatus;
  started_at: string;
  duration_ms: number | null;
  evidence_ids: string[];
}

export interface RunError {
  code: string;
  message: string;
  step: string | null;
  retryable: boolean;
}

export interface InvestigationResult {
  contract_version: string;
  run_id: string;
  demo_mode: boolean;
  claims: Claim[];
  assessed_claims: AssessedClaim[];
  evidence: EvidenceRecord[];
  overall_outcome: OverallOutcome;
  authenticity_status: AuthenticityStatus;
  coverage: Coverage;
  recommended_actions: string[];
  confirmation_route: ConfirmationRoute | null;
  tool_trace: ToolCall[];
  errors: RunError[];
}

export interface RunEvent {
  run_id: string;
  sequence: number;
  step: string;
  status: EventStatus;
  public_message: string;
  timestamp: string;
}

export interface RunSnapshot {
  contract_version: string;
  run_id: string;
  case_id: number;
  version: number;
  previous_run_id: string | null;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  events: RunEvent[];
  report: InvestigationResult | null;
  errors: RunError[];
}

export interface ErrorResponse {
  detail: string;
}
