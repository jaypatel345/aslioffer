import React, { useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, HelpCircle, MinusCircle, XCircle, ExternalLink, ListChecks, PhoneCall, Search } from 'lucide-react';
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

const STATUS_ICON = {
  SUPPORTED: CheckCircle2,
  CONTRADICTED: XCircle,
  UNRESOLVED: HelpCircle,
  NOT_CHECKED: MinusCircle,
} as const;

const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
};

const EvidenceItem: React.FC<{ ev: EvidenceRecord }> = ({ ev }) => {
  const relation = RELATION[ev.relation];
  return (
    <li className="py-3 first:pt-0 last:pb-0 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip className={TONE_CLASSES[relation.tone].chip}>{relation.label}</Chip>
        <span className="text-slate-500">
          {SOURCE_KIND[ev.source_kind]} · {SOURCE_TIER[ev.source_tier]}
        </span>
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
      {ev.source_url ? (
        <a
          href={ev.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 font-medium text-slate-900 hover:text-emerald-700 inline-flex items-start gap-1 break-words"
        >
          {ev.title}
          <ExternalLink className="w-3 h-3 mt-0.5 shrink-0 text-slate-400" />
        </a>
      ) : (
        <p className="mt-1.5 font-medium text-slate-900">{ev.title}</p>
      )}
      {ev.quote_or_snippet && <p className="mt-1 text-slate-600 leading-relaxed">{ev.quote_or_snippet}</p>}
      <div className="mt-1 text-[11px] text-slate-400 flex flex-wrap gap-x-2">
        {ev.source_url && <span className="print:hidden">{hostOf(ev.source_url)}</span>}
        {ev.source_url && <span className="hidden print:inline break-all">{ev.source_url}</span>}
        <span>Retrieved {formatTime(ev.retrieved_at)}</span>
        {ev.query && <span>Search: “{ev.query}”</span>}
      </div>
    </li>
  );
};

const ClaimRow: React.FC<{ claim: Claim; assessment?: AssessedClaim; evidence: EvidenceRecord[] }> = ({
  claim,
  assessment,
  evidence,
}) => {
  const statusKey = assessment?.status ?? 'NOT_CHECKED';
  const status = CLAIM_STATUS[statusKey];
  const tone = TONE_CLASSES[status.tone];
  const Icon = STATUS_ICON[statusKey];
  // Problems open by default so the reader sees them without clicking.
  const [open, setOpen] = useState(statusKey === 'CONTRADICTED');

  return (
    <li className="py-5 first:pt-0 last:pb-0 print:break-inside-avoid">
      <div className="flex items-start gap-3">
        <Icon className={`w-5 h-5 mt-0.5 shrink-0 ${tone.text}`} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
            <div className="min-w-0">
              <div className="text-xs text-slate-500">{CLAIM_KIND_LABEL[claim.kind]}</div>
              <div className="text-sm font-semibold text-slate-900 break-words">
                {claim.value ?? <span className="italic font-normal text-slate-500">Not in the offer</span>}
              </div>
            </div>
            <Chip className={tone.chip}>{status.label}</Chip>
          </div>

          {assessment && <p className="mt-2 text-sm text-slate-600 leading-relaxed">{assessment.explanation}</p>}

          {claim.source_quote && (
            <p className="mt-2 text-xs text-slate-500">
              <span className="font-medium text-slate-600">{EXTRACTION_STATUS[claim.extraction_status]}:</span> “
              {claim.source_quote}”
            </p>
          )}

          {evidence.length > 0 && (
            <div className="mt-3">
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                aria-expanded={open}
                className="print:hidden inline-flex items-center gap-1 text-xs font-medium text-slate-700 hover:text-slate-900"
              >
                <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? '' : '-rotate-90'}`} />
                {open ? 'Hide' : 'Show'} {evidence.length} {evidence.length === 1 ? 'source' : 'sources'}
              </button>
              <ul
                className={`${open ? 'block' : 'hidden'} print:block mt-2 rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3 divide-y divide-slate-200`}
              >
                {evidence.map((ev) => (
                  <EvidenceItem key={ev.evidence_id} ev={ev} />
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
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
      <section className={`glass-panel rounded-xl p-6 sm:p-8 border-l-4 ${tone.border}`}>
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div className="min-w-0">
            {meta && <div className="text-xs text-slate-500 font-mono mb-1">{meta}</div>}
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 break-words">{title}</h1>
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
        <section role="status" className="rounded-xl border border-amber-300 bg-amber-50 p-5 text-sm text-amber-900">
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

      <section className="glass-panel rounded-xl p-6 sm:p-8">
        <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-1">
          <ListChecks className="w-5 h-5 text-emerald-600" />
          Claims and evidence
        </h2>
        <p className="text-sm text-slate-500 mb-4">
          Each claim from the offer, what the investigation found, and the sources behind it.
        </p>
        <div className="flex flex-wrap gap-2 mb-6">
          {(['CONTRADICTED', 'UNRESOLVED', 'SUPPORTED', 'NOT_CHECKED'] as const).map((k) => {
            const n = result.claims.filter((c) => (assessmentById.get(c.claim_id)?.status ?? 'NOT_CHECKED') === k).length;
            return n ? (
              <Chip key={k} className={TONE_CLASSES[CLAIM_STATUS[k].tone].chip}>
                {n} {CLAIM_STATUS[k].label.toLowerCase()}
              </Chip>
            ) : null;
          })}
        </div>
        <ul className="divide-y divide-slate-100">
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

      <section className={`glass-panel rounded-xl p-6 sm:p-8 ${highRisk ? 'border-rose-200 bg-rose-50/60' : ''}`}>
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

      <section className="glass-panel rounded-xl p-6 sm:p-8 print:hidden">
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
