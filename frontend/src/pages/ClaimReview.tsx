import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowRight, ChevronDown, FileText, Lock } from 'lucide-react';
import { api, ApiError } from '../services/api';
import { Claim, ClaimKind, ClaimPreview, ConfirmedClaim } from '../types';
import { CLAIM_KIND_LABEL, EXTRACTION_STATUS } from '../report/labels';

// Scam signals stay as the document states them: the user can't edit them away.
const READ_ONLY_KINDS: ClaimKind[] = ['payment_request', 'credential_request'];

interface Draft {
  value: string;
  confirmed: boolean;
}

/** Turn the user's decisions into contract confirmed_claims. Untouched extracted claims send nothing. */
export function toConfirmedClaims(claims: Claim[], drafts: Record<string, Draft>): ConfirmedClaim[] {
  const out: ConfirmedClaim[] = [];
  for (const claim of claims) {
    if (READ_ONLY_KINDS.includes(claim.kind)) continue;
    const draft = drafts[claim.claim_id];
    if (!draft) continue;
    const value = draft.value.trim();
    if (!value) continue; // a value cannot be removed, only corrected
    if (value !== (claim.value ?? '')) {
      out.push({ claim_id: claim.claim_id, kind: claim.kind, value, extraction_status: 'USER_EDITED' });
    } else if (claim.extraction_status === 'UNCERTAIN' && draft.confirmed) {
      out.push({ claim_id: claim.claim_id, kind: claim.kind, value, extraction_status: 'USER_CONFIRMED' });
    }
  }
  return out;
}

export const ClaimReview: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const offerId = Number(id);
  const navigate = useNavigate();
  const [preview, setPreview] = useState<ClaimPreview | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [error, setError] = useState<{ notFound: boolean; message: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showText, setShowText] = useState(false);

  useEffect(() => {
    window.scrollTo(0, 0);
    if (!Number.isInteger(offerId) || offerId <= 0) {
      setError({ notFound: true, message: `"${id ?? ''}" is not a valid case ID.` });
      return;
    }
    api
      .getClaims(offerId)
      .then((data) => {
        setPreview(data);
        setDrafts(Object.fromEntries(data.claims.map((c) => [c.claim_id, { value: c.value ?? '', confirmed: false }])));
      })
      .catch((err: unknown) =>
        setError({
          notFound: err instanceof ApiError && err.isNotFound,
          message: err instanceof Error ? err.message : 'The claims could not be loaded.',
        }),
      );
  }, [offerId]);

  const start = async () => {
    if (!preview) return;
    setSubmitting(true);
    setError(null);
    try {
      const run = await api.startRun(offerId, toConfirmedClaims(preview.claims, drafts));
      navigate(`/offers/${offerId}/report?run=${encodeURIComponent(run.run_id)}`);
    } catch (err) {
      setSubmitting(false);
      setError({ notFound: false, message: err instanceof Error ? err.message : 'The investigation could not start.' });
    }
  };

  if (error && !preview) {
    return (
      <div className="max-w-xl mx-auto py-20 text-center" role="alert">
        <AlertTriangle className="w-8 h-8 text-rose-600 mx-auto mb-3" />
        <h1 className="text-xl font-bold text-slate-900">{error.notFound ? 'Case not found' : 'Claims could not be loaded'}</h1>
        <p className="text-sm text-slate-600 mt-2">{error.message}</p>
        <Link to="/upload" className="inline-block mt-6 px-4 py-2 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white">
          Verify an offer
        </Link>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="py-20 text-center text-sm text-slate-500">
        <div className="w-10 h-10 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        Reading the offer…
      </div>
    );
  }

  const uncertain = preview.claims.filter((c) => c.extraction_status === 'UNCERTAIN').length;

  return (
    <div className="max-w-3xl mx-auto py-8 space-y-6">
      <div>
        <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wide">Step 2 of 3 · Check the details</p>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900 mt-1">Is this what your offer says?</h1>
        <p className="text-sm text-slate-600 mt-2">
          These details were read from your offer. Searches use them, so fix anything that was read wrongly before
          starting. Nothing has been searched yet.
        </p>
        {uncertain > 0 && (
          <p className="mt-3 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
            {uncertain} detail{uncertain > 1 ? 's are' : ' is'} uncertain. Confirm or correct {uncertain > 1 ? 'them' : 'it'}; unconfirmed
            uncertain details are not searched.
          </p>
        )}
      </div>

      <ul className="space-y-3">
        {preview.claims.map((claim) => {
          const draft = drafts[claim.claim_id] ?? { value: '', confirmed: false };
          const readOnly = READ_ONLY_KINDS.includes(claim.kind);
          const isUncertain = claim.extraction_status === 'UNCERTAIN';
          const edited = draft.value.trim() !== (claim.value ?? '') && draft.value.trim() !== '';
          const inputId = `claim-${claim.claim_id}`;
          return (
            <li
              key={claim.claim_id}
              className={`p-4 rounded-xl border ${isUncertain && !edited && !draft.confirmed ? 'border-amber-300 bg-amber-50/50' : 'border-slate-200 bg-white'}`}
            >
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <label htmlFor={inputId} className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  {CLAIM_KIND_LABEL[claim.kind]}
                </label>
                <span className="text-[11px] text-slate-500">
                  {edited ? 'Corrected by you' : EXTRACTION_STATUS[claim.extraction_status]}
                </span>
              </div>
              {readOnly ? (
                <p className="text-sm text-slate-900 flex items-center gap-1.5">
                  <Lock className="w-3.5 h-3.5 text-slate-400" />
                  {claim.value ?? <span className="italic text-slate-500">None found</span>}
                </p>
              ) : (
                <input
                  id={inputId}
                  value={draft.value}
                  placeholder={claim.extraction_status === 'MISSING' ? 'Not found — add it if the offer has it' : ''}
                  onChange={(e) =>
                    setDrafts((d) => ({ ...d, [claim.claim_id]: { ...draft, value: e.target.value } }))
                  }
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 text-sm text-slate-900 focus:outline-none focus:border-emerald-500"
                />
              )}
              {claim.source_quote && (
                <p className="mt-2 text-xs text-slate-500">
                  <FileText className="w-3 h-3 inline mr-1" />
                  From the offer: “{claim.source_quote}”
                </p>
              )}
              {isUncertain && !readOnly && !edited && (
                <label className="mt-2 flex items-center gap-2 text-xs text-slate-700">
                  <input
                    type="checkbox"
                    checked={draft.confirmed}
                    onChange={(e) =>
                      setDrafts((d) => ({ ...d, [claim.claim_id]: { ...draft, confirmed: e.target.checked } }))
                    }
                  />
                  This is correct
                </label>
              )}
              {!readOnly && claim.value && draft.value.trim() === '' && (
                <p className="mt-1 text-[11px] text-slate-500">An empty value keeps what was read from the offer.</p>
              )}
            </li>
          );
        })}
      </ul>

      <div className="glass-panel rounded-xl p-4">
        <button
          type="button"
          onClick={() => setShowText((v) => !v)}
          className="w-full flex items-center justify-between text-sm font-semibold text-slate-700"
          aria-expanded={showText}
        >
          Text that will be investigated
          <ChevronDown className={`w-4 h-4 transition-transform ${showText ? 'rotate-180' : ''}`} />
        </button>
        {showText && (
          <>
            <p className="text-xs text-slate-500 mt-2">ID numbers, bank details and one-time codes are removed before any search.</p>
            <pre className="mt-2 whitespace-pre-wrap text-xs text-slate-700 bg-slate-50 rounded-lg p-3 max-h-80 overflow-auto">
              {preview.text}
            </pre>
          </>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2">
          {error.message}
        </p>
      )}

      <div className="flex justify-end">
        <button
          type="button"
          onClick={start}
          disabled={submitting}
          className="px-5 py-3 rounded-lg bg-slate-900 hover:bg-slate-800 disabled:opacity-60 text-white font-medium text-sm inline-flex items-center gap-2"
        >
          {submitting ? 'Starting…' : 'Start investigation'}
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
