import React, { useMemo, useState } from 'react';
import { Check, Copy, ExternalLink, Mail, ShieldAlert } from 'lucide-react';
import { Claim, EvidenceRecord, InvestigationResult } from '../types';
import { SOURCE_TIER } from '../report/labels';

const SECRET_HINT = /\b(otp|password|pin|cvv|aadhaar|account\s*(no|number))\b/i;

const isUrl = (value: string) => /^https?:\/\//i.test(value);
const isEmail = (value: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value);

function claimValue(claims: Claim[], kind: Claim['kind']) {
  return claims.find((c) => c.kind === kind && c.value)?.value ?? null;
}

/** The employer's website, only when the investigation itself established it from an official source. */
function officialSite(result: InvestigationResult): string | null {
  const employer = result.claims.find((c) => c.kind === 'employer');
  if (!employer) return null;
  const assessed = result.assessed_claims.find((a) => a.claim_id === employer.claim_id);
  if (assessed?.status !== 'SUPPORTED') return null;
  const official = result.evidence.find(
    (e) => assessed.evidence_ids.includes(e.evidence_id) && e.relation === 'SUPPORTS' && e.source_tier === 'OFFICIAL_EMPLOYER' && e.source_url,
  );
  try {
    return official?.source_url ? new URL(official.source_url).hostname : null;
  } catch {
    return null;
  }
}

/** Neutral question for the employer. Never includes contacts taken from the offer. */
function defaultDraft(result: InvestigationResult): string {
  const employer = claimValue(result.claims, 'employer') ?? 'your company';
  const role = claimValue(result.claims, 'role');
  const reference = claimValue(result.claims, 'job_reference');
  return [
    `Hello ${employer} recruitment team,`,
    '',
    `I have received an offer${role ? ` for the ${role} role` : ''}${reference ? ` (reference ${reference})` : ''} ` +
      `that says it comes from ${employer}. Could you please confirm whether this offer was issued by you?`,
    '',
    'I have not shared any payment, bank details or passwords. Thank you.',
    '',
    '[Your name]',
  ].join('\n');
}

/**
 * J5: the employer-published confirmation route and a draft the user reviews and
 * sends themselves. The destination comes only from `confirmation_route`, which
 * the investigator must back with retrieved evidence — never from a contact or
 * link in the offer. Nothing is sent automatically.
 */
export const ConfirmationPanel: React.FC<{ result: InvestigationResult }> = ({ result }) => {
  const route = result.confirmation_route;
  const evidence: EvidenceRecord | undefined = route
    ? result.evidence.find((e) => e.evidence_id === route.evidence_id)
    : undefined;
  const initial = useMemo(() => route?.draft_message || defaultDraft(result), [result, route]);
  const [draft, setDraft] = useState(initial);
  const site = route ? null : officialSite(result);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const mentionsSecrets = SECRET_HINT.test(draft);

  return (
    <section className="glass-panel rounded-xl p-6 sm:p-8 print:break-inside-avoid">
      <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
        <Mail className="w-5 h-5 text-emerald-600" />
        Confirm with the employer
      </h2>
      <p className="text-xs text-slate-500 mt-1 mb-5">
        Only the employer can confirm an offer. Use a channel the employer publishes itself, never a phone number,
        email or link given in the offer.
      </p>

      {route ? (
        <div className="p-4 rounded-xl bg-emerald-50/60 border border-emerald-200 text-sm mb-5">
          <div className="text-xs font-semibold text-emerald-800 uppercase tracking-wide mb-1">
            {route.channel.replace(/_/g, ' ')}
          </div>
          {isUrl(route.destination) ? (
            <a
              href={route.destination}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-emerald-700 hover:underline break-all inline-flex items-center gap-1"
            >
              {route.destination}
              <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
          ) : (
            <span className="font-semibold text-slate-900 break-all">{route.destination}</span>
          )}
          {evidence && (
            <p className="text-xs text-slate-600 mt-2">
              Found in: {evidence.title} · {SOURCE_TIER[evidence.source_tier]}
              {evidence.source_url && (
                <>
                  {' · '}
                  <a href={evidence.source_url} target="_blank" rel="noopener noreferrer" className="underline break-all">
                    {evidence.source_url}
                  </a>
                </>
              )}
            </p>
          )}
        </div>
      ) : site ? (
        <div className="p-4 rounded-xl bg-emerald-50/60 border border-emerald-200 text-sm text-slate-700 mb-5">
          <div className="text-xs font-semibold text-emerald-800 uppercase tracking-wide mb-1">Official website</div>
          <span className="font-semibold text-emerald-800">{site}</span>
          <p className="text-xs text-slate-600 mt-1">
            Our search found this as the employer’s official website, but no specific confirmation contact. Type the
            address into your browser yourself (don’t follow links in the offer) and use the contact or careers page
            there. You can use the draft below.
          </p>
        </div>
      ) : (
        <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-700 mb-5">
          <strong>No employer-published confirmation channel was found.</strong> Look up the employer’s official
          website yourself (type the address, don’t follow links in the offer) and use the contact or careers page
          listed there. You can use the draft below.
        </div>
      )}

      <label htmlFor="confirmation-draft" className="text-xs font-semibold text-slate-600 block mb-1.5">
        Draft message — review and edit before you send it yourself
      </label>
      <textarea
        id="confirmation-draft"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={8}
        className="w-full px-3 py-3 rounded-xl bg-white border border-slate-300 text-sm text-slate-900 focus:outline-none focus:border-emerald-500 leading-relaxed print:hidden"
      />
      <pre className="hidden print:block whitespace-pre-wrap text-sm">{draft}</pre>
      {mentionsSecrets && (
        <p className="mt-2 text-xs text-rose-700 flex items-center gap-1.5">
          <ShieldAlert className="w-3.5 h-3.5" />
          Never send OTPs, passwords, PINs, Aadhaar or bank account numbers to confirm an offer.
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3 print:hidden">
        <button
          type="button"
          onClick={copy}
          className="px-3.5 py-2 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white inline-flex items-center gap-1.5"
        >
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
          {copied ? 'Copied' : 'Copy draft'}
        </button>
        {route && isEmail(route.destination) && (
          <a
            href={`mailto:${route.destination}?subject=${encodeURIComponent('Offer confirmation request')}&body=${encodeURIComponent(draft)}`}
            className="px-3.5 py-2 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white"
          >
            Open in my email app
          </a>
        )}
        <span className="text-[11px] text-slate-500">AsliOffer never sends messages for you.</span>
      </div>
    </section>
  );
};
