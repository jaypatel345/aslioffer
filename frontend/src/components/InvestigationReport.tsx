import React, { useState } from 'react';
import { AlertTriangle, ChevronDown, ExternalLink, FileText, ListChecks, PhoneCall, Search } from 'lucide-react';
import { AssessedClaim, Claim, EvidenceRecord, InvestigationResult } from '../types';
import { OutcomeBadge } from './OutcomeBadge';
import { ConfirmationPanel } from './ConfirmationPanel';
import {
  CLAIM_KIND_LABEL,
  CLAIM_STATUS,
  EXTRACTION_STATUS,
  OUTCOME,
  RELATION,
  RETRIEVAL,
  SOURCE_KIND,
  SOURCE_TIER,
  TONE_CLASSES,
  formatTime,
} from '../report/labels';

const Chip: React.FC<{ className: string; children: React.ReactNode }> = ({ className, children }) => (
  <span className={`inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-full border ${className}`}>
    {children}
  </span>
);

const EvidenceItem: React.FC<{ ev: EvidenceRecord }> = ({ ev }) => (
  <li className="p-3 rounded-xl bg-white border border-slate-200 text-xs space-y-1.5">
    <div className="flex flex-wrap items-center gap-1.5">
      <Chip className={TONE_CLASSES[RELATION[ev.relation].tone].chip}>{RELATION[ev.relation].label}</Chip>
      <Chip className="bg-slate-50 text-slate-600 border-slate-200">{SOURCE_KIND[ev.source_kind]}</Chip>
      <Chip className="bg-slate-50 text-slate-600 border-slate-200">{SOURCE_TIER[ev.source_tier]}</Chip>
      {ev.retrieval_status !== 'LIVE' && (
        <Chip
          className={
            ev.retrieval_status === 'FAILED'
              ? TONE_CLASSES.rose.chip
              : ev.retrieval_status === 'DEMO'
              ? TONE_CLASSES.amber.chip
              : 'bg-slate-50 text-slate-600 border-slate-200'
          }
        >
          {RETRIEVAL[ev.retrieval_status]}
        </Chip>
      )}
    </div>
    <p className="font-semibold text-slate-800">{ev.title}</p>
    {ev.quote_or_snippet && <blockquote className="text-slate-600 border-l-2 border-slate-300 pl-2">{ev.quote_or_snippet}</blockquote>}
    <div className="text-[11px] text-slate-500 flex flex-wrap gap-x-3 gap-y-0.5">
      {ev.source_url && (
        <a
          href={ev.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-emerald-700 hover:underline inline-flex items-center gap-1 break-all"
        >
          {ev.source_url}
          <ExternalLink className="w-3 h-3 shrink-0" />
        </a>
      )}
      <span>Retrieved {formatTime(ev.retrieved_at)}</span>
      {ev.query && <span>Query: “{ev.query}”</span>}
    </div>
  </li>
);

const ClaimRow: React.FC<{ claim: Claim; assessment?: AssessedClaim; evidence: EvidenceRecord[] }> = ({
  claim,
  assessment,
  evidence,
}) => {
  const status = assessment ? CLAIM_STATUS[assessment.status] : CLAIM_STATUS.NOT_CHECKED;
  const tone = TONE_CLASSES[status.tone];
  return (
    <li className={`p-4 sm:p-5 rounded-xl bg-slate-50/80 border border-slate-200 border-l-4 ${tone.border} print:break-inside-avoid`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{CLAIM_KIND_LABEL[claim.kind]}</div>
          <div className="text-sm font-bold text-slate-900 break-words">
            {claim.value ?? <span className="italic font-normal text-slate-500">Not in the offer</span>}
          </div>
        </div>
        <Chip className={tone.chip}>{status.label}</Chip>
      </div>
      {claim.source_quote && (
        <blockquote className="mt-2 text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-3 py-2">
          <FileText className="w-3 h-3 inline mr-1 text-slate-400" />“{claim.source_quote}”
        </blockquote>
      )}
      <p className="mt-1 text-[11px] text-slate-500">{EXTRACTION_STATUS[claim.extraction_status]}</p>
      {assessment && <p className="mt-2 text-sm text-slate-700 leading-relaxed">{assessment.explanation}</p>}
      {evidence.length > 0 && (
        <ul className="mt-3 space-y-2">
          {evidence.map((ev) => (
            <EvidenceItem key={ev.evidence_id} ev={ev} />
          ))}
        </ul>
      )}
    </li>
  );
};

interface Props {
  result: InvestigationResult;
  title: string;
  /** Extra controls rendered in the header (re-run, export, delete). */
  actions?: React.ReactNode;
  meta?: React.ReactNode;
}

/** Contract-v1 report. No score or confidence percentage anywhere: none is calibrated. */
export const InvestigationReport: React.FC<Props> = ({ result, title, actions, meta }) => {
  const [showTrace, setShowTrace] = useState(false);
  const outcome = OUTCOME[result.overall_outcome];
  const tone = TONE_CLASSES[outcome.tone];
  const evidenceById = new Map(result.evidence.map((e) => [e.evidence_id, e]));
  const assessmentById = new Map(result.assessed_claims.map((a) => [a.claim_id, a]));
  const evidenceFor = (claim: Claim) => {
    const cited = (assessmentById.get(claim.claim_id)?.evidence_ids ?? [])
      .map((id) => evidenceById.get(id))
      .filter((e): e is EvidenceRecord => Boolean(e));
    // Also show records about this claim the assessment did not cite (e.g. failed lookups).
    const extra = result.evidence.filter((e) => e.claim_id === claim.claim_id && !cited.includes(e));
    return [...cited, ...extra];
  };
  const { coverage } = result;
  const highRisk = result.overall_outcome === 'HIGH_RISK';

  return (
    <div className="space-y-6">
      <section className={`glass-panel rounded-2xl p-6 sm:p-8 border-l-4 ${tone.border}`}>
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div className="min-w-0">
            {meta && <div className="text-xs text-slate-500 font-mono mb-1">{meta}</div>}
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 break-words">{title}</h1>
          </div>
          <OutcomeBadge outcome={result.overall_outcome} size="lg" />
        </div>
        <p className="mt-4 text-sm sm:text-base text-slate-700 leading-relaxed">{outcome.summary}</p>
        <p className="mt-2 text-xs text-slate-500">
          Authenticity: <strong>unconfirmed</strong>. Only the employer can confirm an offer.
          {result.demo_mode && ' This run used demo data, not live search.'}
        </p>

        <dl className="mt-5 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
          {[
            ['Claims checked', `${coverage.checked_claims} of ${coverage.total_claims}`],
            ['Unresolved', String(coverage.unresolved_claims)],
            ['Failed checks', String(coverage.failed_checks)],
            ['Sources cited', String(result.evidence.filter((e) => e.source_url).length)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl bg-slate-50 border border-slate-200 p-3">
              <dt className="text-[11px] text-slate-500">{label}</dt>
              <dd className="text-lg font-bold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-[11px] text-slate-500">Coverage shows how complete the checks were. It is not a fraud probability.</p>
        {actions && <div className="mt-5 flex flex-wrap gap-2 print:hidden">{actions}</div>}
      </section>

      {result.errors.length > 0 && (
        <section role="status" className="rounded-2xl border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900">
          <h2 className="font-bold flex items-center gap-2 mb-2">
            <AlertTriangle className="w-4 h-4" />
            Some checks did not complete
          </h2>
          <ul className="list-disc pl-5 space-y-1 text-xs">
            {result.errors.map((e, i) => (
              <li key={i}>
                {e.message}
                {e.retryable && ' (may work if you run the investigation again)'}
              </li>
            ))}
          </ul>
          <p className="text-xs mt-2">Claims these checks would have covered are shown as unresolved, not as evidence either way.</p>
        </section>
      )}

      <section className="glass-panel rounded-2xl p-6 sm:p-8">
        <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-1">
          <ListChecks className="w-5 h-5 text-emerald-600" />
          Claims and evidence
        </h2>
        <p className="text-xs text-slate-500 mb-5">
          Each claim from the offer, what the investigation found, and the sources behind it.
        </p>
        <ul className="space-y-3">
          {result.claims.map((claim) => (
            <ClaimRow
              key={claim.claim_id}
              claim={claim}
              assessment={assessmentById.get(claim.claim_id)}
              evidence={evidenceFor(claim)}
            />
          ))}
        </ul>
      </section>

      <section className={`glass-panel rounded-2xl p-6 sm:p-8 ${highRisk ? 'border-rose-200 bg-rose-50/60' : ''}`}>
        <h2 className="text-lg font-bold text-slate-900 mb-4">Recommended next steps</h2>
        <ol className="space-y-2.5">
          {result.recommended_actions.map((action, idx) => (
            <li key={idx} className="flex items-start gap-2.5 text-sm text-slate-700 leading-relaxed">
              <span className="w-5 h-5 rounded-full bg-slate-100 flex items-center justify-center text-xs font-semibold text-emerald-700 shrink-0 mt-0.5">
                {idx + 1}
              </span>
              <span>{action}</span>
            </li>
          ))}
        </ol>
        {highRisk && (
          <div className="mt-5 pt-4 border-t border-rose-200 flex flex-wrap items-center gap-3 text-xs">
            <span className="inline-flex items-center gap-1.5 font-bold text-rose-700">
              <PhoneCall className="w-3.5 h-3.5" /> National Cyber Helpline: 1930
            </span>
            <a
              href="https://cybercrime.gov.in"
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-bold inline-flex items-center gap-1"
            >
              Report at cybercrime.gov.in <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        )}
      </section>

      <ConfirmationPanel key={result.run_id} result={result} />

      <section className="glass-panel rounded-2xl p-6 sm:p-8 print:hidden">
        <button
          type="button"
          onClick={() => setShowTrace((v) => !v)}
          className="w-full flex items-center justify-between text-left"
          aria-expanded={showTrace}
        >
          <span className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <Search className="w-5 h-5 text-emerald-600" />
            Searches run ({result.tool_trace.length})
          </span>
          <ChevronDown className={`w-5 h-5 text-slate-500 transition-transform ${showTrace ? 'rotate-180' : ''}`} />
        </button>
        {showTrace && (
          <ol className="mt-4 space-y-2">
            {result.tool_trace.length === 0 && <li className="text-xs text-slate-500">No external searches were made.</li>}
            {result.tool_trace.map((call, i) => (
              <li key={i} className="text-xs p-3 rounded-lg bg-slate-50 border border-slate-200">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-semibold text-slate-800">{call.tool}</span>
                  <Chip className={call.status === 'FAILED' ? TONE_CLASSES.rose.chip : 'bg-white text-slate-600 border-slate-200'}>
                    {call.status.toLowerCase()}
                  </Chip>
                  {call.duration_ms !== null && <span className="text-slate-500">{call.duration_ms} ms</span>}
                </div>
                {call.query && <p className="mt-1 text-slate-700">“{call.query}”</p>}
                <p className="mt-0.5 text-slate-500">Why: {call.reason}</p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
};
