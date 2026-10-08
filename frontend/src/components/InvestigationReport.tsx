import React, { useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  Flag,
  Gauge,
  HelpCircle,
  ListChecks,
  MinusCircle,
  PhoneCall,
  Search,
  Sparkles,
} from 'lucide-react';
import { AssessedClaim, Claim, EvidenceRecord, InvestigationResult } from '../types';
import { OutcomeBadge } from './OutcomeBadge';
import { ConfirmationPanel } from './ConfirmationPanel';
import {
  CLAIM_KIND_LABEL,
  EXTRACTION_STATUS,
  OUTCOME,
  RELATION,
  RETRIEVAL,
  SOURCE_KIND,
  SOURCE_TIER,
  TONE_CLASSES,
  Tone,
  PlainVerdict,
  formatTime,
  isDemandKind,
  plainExplanation,
  plainStatus,
} from '../report/labels';

const Chip: React.FC<{ className: string; children: React.ReactNode }> = ({ className, children }) => (
  <span className={`inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-full border ${className}`}>
    {children}
  </span>
);

const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
};

const VERDICT_ICON: Record<PlainVerdict, React.ElementType> = {
  red_flag: Flag,
  good: CheckCircle2,
  unconfirmed: HelpCircle,
  not_checked: MinusCircle,
};

const VERDICT_ORDER: PlainVerdict[] = ['red_flag', 'good', 'unconfirmed', 'not_checked'];

// ---------------------------------------------------------------- key findings

interface Finding {
  tone: Tone;
  Icon: React.ElementType;
  title: string;
  detail: string;
}

const clip = (text: string, max = 160) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);

/** Host of the first official-employer source the assessment itself cited for a claim. */
function officialHost(assessment: AssessedClaim | undefined, evidenceById: Map<string, EvidenceRecord>) {
  const ev = assessment?.evidence_ids
    .map((id) => evidenceById.get(id))
    .find((e) => e && e.relation === 'SUPPORTS' && e.source_tier === 'OFFICIAL_EMPLOYER' && e.source_url);
  return ev?.source_url ? hostOf(ev.source_url) : null;
}

/**
 * The few facts a reader needs first, derived only from the assessed claims and
 * their cited evidence. Nothing here is inferred beyond what the report states below.
 */
function keyFindings(result: InvestigationResult, assessmentById: Map<string, AssessedClaim>, evidenceById: Map<string, EvidenceRecord>) {
  const red: Finding[] = [];
  const good: Finding[] = [];
  const unconfirmed: string[] = [];
  const byKind = (kind: Claim['kind']) => result.claims.find((c) => c.kind === kind);

  for (const claim of result.claims) {
    const assessment = assessmentById.get(claim.claim_id);
    const plain = plainStatus(claim, assessment);
    const label = CLAIM_KIND_LABEL[claim.kind];
    if (plain.verdict === 'red_flag') {
      if (claim.kind === 'payment_request') {
        red.push({ tone: 'rose', Icon: Flag, title: 'Asks you to pay money', detail: `“${clip(claim.value ?? '')}” Genuine employers never charge candidates.` });
      } else if (claim.kind === 'credential_request') {
        red.push({ tone: 'rose', Icon: Flag, title: 'Asks for passwords, OTPs or bank details', detail: `“${clip(claim.value ?? '')}” Never share these.` });
      } else if (claim.kind === 'sender_email') {
        red.push({ tone: 'rose', Icon: Flag, title: "Recruiter's email doesn't match the company", detail: assessment?.explanation ?? '' });
      } else {
        red.push({ tone: 'rose', Icon: Flag, title: `${label} doesn't match public records`, detail: assessment?.explanation ?? '' });
      }
    } else if (plain.verdict === 'good' && claim.value) {
      const host = officialHost(assessment, evidenceById);
      if (claim.kind === 'employer') {
        good.push({ tone: 'emerald', Icon: CheckCircle2, title: `${claim.value} is a real company`, detail: host ? `Official website found: ${host}` : 'Its public footprint was found.' });
      } else if (claim.kind === 'sender_email') {
        good.push({ tone: 'emerald', Icon: CheckCircle2, title: "Recruiter's email is published by the company", detail: host ? `Listed on ${host}, the employer's own website.` : 'Listed on the employer’s own website.' });
      } else {
        good.push({ tone: 'emerald', Icon: CheckCircle2, title: `${label} confirmed`, detail: host ? `Found on ${host}.` : clip(assessment?.explanation ?? '') });
      }
    } else if (plain.verdict === 'unconfirmed') {
      unconfirmed.push(label);
    }
  }

  const employer = byKind('employer');
  const asksForMoney = result.claims.some((c) => isDemandKind(c.kind) && c.value);
  if (!asksForMoney) {
    good.push({ tone: 'emerald', Icon: CheckCircle2, title: 'No payment or bank details requested', detail: 'The offer does not ask you for money, OTPs or passwords.' });
  }

  // Money and credential demands are the strongest signs; show them first.
  const demandFirst = (f: Finding) => (f.title.startsWith('Asks') ? 0 : 1);
  const findings = [...red.sort((a, b) => demandFirst(a) - demandFirst(b)), ...good];
  // Threads where people ask whether this employer is genuine: a caution, not proof.
  const discussions = result.evidence.filter((e) => e.source_url && e.query?.endsWith('scam or legit'));
  if (discussions.length) {
    const first = discussions[0];
    findings.splice(red.length, 0, {
      tone: 'amber',
      Icon: AlertTriangle,
      title: `People online are asking if ${employer?.value ?? 'this company'} is a scam`,
      detail: `“${clip(first.title, 90)}” on ${hostOf(first.source_url as string)}${discussions.length > 1 ? ` and ${discussions.length - 1} more` : ''}. Read before you share documents or pay anything.`,
    });
  }
  if (!employer?.value) {
    findings.push({ tone: 'amber', Icon: HelpCircle, title: 'No company name we could check', detail: 'The message does not clearly name an employer, so its public footprint could not be looked up.' });
  }
  if (unconfirmed.length) {
    findings.push({
      tone: 'amber',
      Icon: HelpCircle,
      title: `Couldn't confirm: ${unconfirmed.join(', ')}`,
      detail: 'Public records neither proved nor disproved these. That alone is not a scam sign.',
    });
  }
  return findings;
}

// ---------------------------------------------------------------- evidence + claim rows

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
  const plain = plainStatus(claim, assessment);
  const tone = TONE_CLASSES[plain.tone];
  const [open, setOpen] = useState(false);
  const showExplanation = assessment && !(isDemandKind(claim.kind) && !claim.value);
  const Icon = VERDICT_ICON[plain.verdict];

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
            <Chip className={tone.chip}>{plain.label}</Chip>
          </div>

          {showExplanation && (
            <p className="mt-2 text-sm text-slate-700 leading-relaxed" title={assessment.explanation}>
              {plainExplanation(claim, assessment)}
            </p>
          )}

          {claim.source_quote && claim.source_quote !== claim.value && (
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

// ---------------------------------------------------------------- report

interface Props {
  result: InvestigationResult;
  title: string;
  /** Extra controls rendered in the header (re-run, export, delete). */
  actions?: React.ReactNode;
  meta?: React.ReactNode;
}

/**
 * Contract-v1 report, ordered for a first-time reader: verdict, the few facts that
 * explain it, what to do, then every claim, and finally how complete the check was.
 * No score or confidence percentage anywhere: none is calibrated.
 */
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
  const findings = keyFindings(result, assessmentById, evidenceById);
  const sortedClaims = [...result.claims].sort(
    (a, b) =>
      VERDICT_ORDER.indexOf(plainStatus(a, assessmentById.get(a.claim_id)).verdict) -
      VERDICT_ORDER.indexOf(plainStatus(b, assessmentById.get(b.claim_id)).verdict),
  );
  const [firstStep, ...laterSteps] = result.recommended_actions;

  return (
    <div className="space-y-6">
      {/* 1. Verdict */}
      <section className={`glass-panel rounded-xl p-6 sm:p-8 border-l-4 ${tone.border}`}>
        {meta && <div className="text-xs text-slate-500 font-mono mb-2">{meta}</div>}
        <div className="flex flex-col-reverse sm:flex-row sm:items-start justify-between gap-3">
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-slate-900 break-words">{title}</h1>
          <OutcomeBadge outcome={result.overall_outcome} size="lg" />
        </div>
        <p className={`mt-4 text-base sm:text-lg font-semibold leading-snug ${tone.text}`}>{outcome.summary}</p>
        <p className="mt-2 text-xs text-slate-500">
          Authenticity: <strong>unconfirmed</strong>. Only the employer can confirm an offer.
          {result.demo_mode && ' This run used demo data, not live search.'}
        </p>
        {actions && <div className="mt-5 flex flex-wrap gap-2 print:hidden">{actions}</div>}
      </section>

      {/* 2. Key findings */}
      <section className="glass-panel rounded-xl p-6 sm:p-8">
        <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-4">
          <Sparkles className="w-5 h-5 text-emerald-600" />
          Key findings
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2">
          {findings.map((f, i) => {
            const t = TONE_CLASSES[f.tone];
            return (
              <li key={i} className={`rounded-xl border p-4 ${t.chip} print:break-inside-avoid`}>
                <div className="flex items-start gap-2.5">
                  <f.Icon className="w-5 h-5 shrink-0 mt-0.5" aria-hidden />
                  <div className="min-w-0">
                    <p className="font-bold text-sm text-slate-900">{f.title}</p>
                    {f.detail && <p className="mt-1 text-xs text-slate-700 leading-relaxed break-words">{f.detail}</p>}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
        {result.errors.length > 0 && (
          <p className="mt-4 text-xs text-amber-800 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            Some checks did not finish. Details are at the end of this report.
          </p>
        )}
      </section>

      {/* 3. What to do now */}
      {firstStep && (
        <section className={`glass-panel rounded-xl p-6 sm:p-8 ${highRisk ? 'border-rose-200 bg-rose-50/60' : ''}`}>
          <h2 className="text-lg font-bold text-slate-900 mb-3">What to do now</h2>
          <p className={`text-sm font-semibold leading-relaxed ${highRisk ? 'text-rose-800' : 'text-slate-800'}`}>{firstStep}</p>
          {laterSteps.length > 0 && (
            <ol className="mt-4 space-y-2.5">
              {laterSteps.map((action, idx) => (
                <li key={idx} className="flex items-start gap-2.5 text-sm text-slate-700 leading-relaxed">
                  <span className="w-5 h-5 rounded-full bg-slate-100 flex items-center justify-center text-xs font-semibold text-emerald-700 shrink-0 mt-0.5">
                    {idx + 2}
                  </span>
                  <span>{action}</span>
                </li>
              ))}
            </ol>
          )}
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
      )}

      {/* 4. Confirm with the employer */}
      <ConfirmationPanel key={result.run_id} result={result} />

      {/* 5. Everything we checked */}
      <section className="glass-panel rounded-xl p-6 sm:p-8">
        <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-1">
          <ListChecks className="w-5 h-5 text-emerald-600" />
          Everything we checked
        </h2>
        <p className="text-sm text-slate-500 mb-4">
          Each detail from the offer, what we found, and the sources behind it. Red flags are listed first.
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 mb-6 text-xs text-slate-600">
          <span className="inline-flex items-center gap-1"><Flag className="w-3.5 h-3.5 text-rose-700" /> Red flag</span>
          <span className="inline-flex items-center gap-1"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-700" /> Confirmed by public sources</span>
          <span className="inline-flex items-center gap-1"><HelpCircle className="w-3.5 h-3.5 text-amber-800" /> Couldn't confirm (not a scam sign by itself)</span>
          <span className="inline-flex items-center gap-1"><MinusCircle className="w-3.5 h-3.5 text-slate-500" /> Not checked</span>
        </div>
        <ul className="divide-y divide-slate-100">
          {sortedClaims.map((claim) => (
            <ClaimRow
              key={claim.claim_id}
              claim={claim}
              assessment={assessmentById.get(claim.claim_id)}
              evidence={evidenceFor(claim)}
            />
          ))}
        </ul>
      </section>

      {/* 6. How complete was this check? */}
      <section className="glass-panel rounded-xl p-6 sm:p-8">
        <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-1">
          <Gauge className="w-5 h-5 text-emerald-600" />
          How complete was this check?
        </h2>
        <p className="text-sm text-slate-500 mb-4">This shows how much could be checked. It is not a fraud probability.</p>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
          {[
            ['Details checked', `${coverage.checked_claims} of ${coverage.total_claims}`],
            ["Couldn't confirm", String(coverage.unresolved_claims)],
            ['Searches that failed', String(coverage.failed_checks)],
            ['Sources cited', String(result.evidence.filter((e) => e.source_url).length)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl bg-slate-50 border border-slate-200 p-3">
              <dt className="text-[11px] text-slate-500">{label}</dt>
              <dd className="text-lg font-bold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>

        {result.errors.length > 0 && (
          <div role="status" className="mt-5 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
            <p className="font-bold flex items-center gap-2 mb-2">
              <AlertTriangle className="w-4 h-4" />
              Some checks did not complete
            </p>
            <ul className="list-disc pl-5 space-y-1 text-xs">
              {result.errors.map((e, i) => (
                <li key={i}>
                  {e.message}
                  {e.retryable && ' (may work if you run the investigation again)'}
                </li>
              ))}
            </ul>
            <p className="text-xs mt-2">Details these checks would have covered are shown as “couldn't confirm”, not as evidence either way.</p>
          </div>
        )}

        <div className="mt-5 print:hidden">
          <button
            type="button"
            onClick={() => setShowTrace((v) => !v)}
            className="w-full flex items-center justify-between text-left"
            aria-expanded={showTrace}
          >
            <span className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Search className="w-4 h-4 text-emerald-600" />
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
        </div>
      </section>
    </div>
  );
};
