import { InvestigationResult } from '../types';
import highRisk from './v1/high_risk_impersonation.json';
import sparse from './v1/cannot_verify_sparse_startup.json';
import outage from './v1/cannot_verify_provider_outage.json';
import noSignals from './v1/no_strong_risk_signals.json';

/**
 * Illustrative sample reports, copied from the contract-v1 example payloads in
 * docs/contract/v1/examples/. Every company, person and domain in them is
 * synthetic (*.example). They are only reachable through /samples/:key, which
 * shows a banner saying so, and are never substituted for a real case.
 */
export interface SampleEntry {
  key: string;
  label: string;
  title: string;
  result: InvestigationResult;
}

const entries: SampleEntry[] = [
  { key: 'impersonation', label: 'impersonation with a fee demand', title: 'Nimbus Infotech Graduate Engineer Trainee offer', result: highRisk as InvestigationResult },
  { key: 'sparse-startup', label: 'small startup with little public footprint', title: 'Coorix Labs Backend Developer Intern offer', result: sparse as InvestigationResult },
  { key: 'provider-outage', label: 'search provider outage', title: 'Vardhan Analytics Data Analyst offer', result: outage as InvestigationResult },
  { key: 'no-strong-signals', label: 'consistent public evidence', title: 'Kestrel Systems Associate Consultant offer', result: noSignals as InvestigationResult },
];

export const SAMPLE_REPORTS: Record<string, SampleEntry> = Object.fromEntries(entries.map((e) => [e.key, e]));
