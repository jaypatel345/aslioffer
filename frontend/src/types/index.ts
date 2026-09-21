export type RiskLevel = 'VERIFIED' | 'NEEDS_REVIEW' | 'HIGH_RISK' | 'CANNOT_VERIFY';

export interface VerdictReason {
  code: string;
  reason: string;
}

export interface ExtractedEntities {
  company_name?: string;
  recruiter_name?: string;
  recruiter_email?: string;
  recruiter_phone?: string;
  role_title?: string;
  offered_salary?: string;
  location?: string;
  demanded_fee?: string;
  payment_method?: string;
  flags: string[];
}

export interface EvidenceItem {
  source_url: string;
  title: string;
  description: string;
  evidence_type: 'COMPANY' | 'RECRUITER' | 'SALARY' | 'SCAM_REPORT' | 'DOMAIN' | string;
  confidence: number;
}

export interface AgentFinding {
  agent_name: string;
  verdict: string;
  confidence: number;
  summary: string;
  evidence: EvidenceItem[];
  details: Record<string, any>;
}

export interface VerificationReport {
  offer_id: number;
  title: string;
  risk_level: RiskLevel;
  risk_score: number;
  summary: string;
  extracted_entities: ExtractedEntities;
  findings: AgentFinding[];
  red_flags: string[];
  green_flags: string[];
  official_company_info: {
    name?: string;
    website?: string;
    careers_url?: string;
    mca_status?: string;
    recruitment_policy?: string;
  };
  recommended_actions: string[];
  reason_details?: VerdictReason[];
  generated_at: string;
}

export interface Offer {
  id: number;
  title: string;
  source_type: string;
  raw_content: string;
  risk_score?: number;
  status: string;
  risk_level?: RiskLevel;
  created_at: string;
}

export interface OfferUploadResponse {
  offer_id: number;
  title: string;
  status: string;
  message: string;
}
