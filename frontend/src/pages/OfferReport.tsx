import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, Download, Printer, RefreshCw, Trash2 } from 'lucide-react';
import { api, ApiError } from '../services/api';
import { lastReport } from '../services/lastReport';
import { ConfirmedClaim, InvestigationResult, RunSnapshot } from '../types';
import { InvestigationReport } from '../components/InvestigationReport';
import { RunProgress } from '../components/RunProgress';
import { buildMarkdownReport, downloadText } from '../report/exportReport';
import { formatTime } from '../report/labels';

const POLL_MS = 1500;
const isActive = (run: RunSnapshot) => run.status === 'QUEUED' || run.status === 'RUNNING';
const hasReport = (run: RunSnapshot) => run.status === 'COMPLETED' || run.status === 'PARTIAL';

/** The user's claim decisions from a finished report, so "run again" keeps them. */
function confirmationsFrom(result: InvestigationResult): ConfirmedClaim[] {
  return result.claims
    .filter((c) => (c.extraction_status === 'USER_CONFIRMED' || c.extraction_status === 'USER_EDITED') && c.value)
    .map((c) => ({
      claim_id: c.claim_id,
      kind: c.kind,
      value: c.value as string,
      extraction_status: c.extraction_status as ConfirmedClaim['extraction_status'],
    }));
}

type View =
  | { kind: 'loading' }
  | { kind: 'error'; notFound: boolean; message: string }
  | { kind: 'no-report' }
  | { kind: 'progress'; run: RunSnapshot }
  | { kind: 'failed'; run: RunSnapshot; previous: RunSnapshot | null }
  | { kind: 'report'; run: RunSnapshot };

export const OfferReport: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const parsedId = Number(id);
  const offerId = Number.isInteger(parsedId) && parsedId > 0 ? parsedId : null;
  const [params, setParams] = useSearchParams();
  const runParam = params.get('run');
  const navigate = useNavigate();

  const [view, setView] = useState<View>({ kind: 'loading' });
  const [title, setTitle] = useState('Offer report');
  const [history, setHistory] = useState<RunSnapshot[]>([]);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [includeContacts, setIncludeContacts] = useState(false);
  const timer = useRef<number | null>(null);

  const fail = (err: unknown) => {
    const notFound = err instanceof ApiError && err.isNotFound;
    if (notFound && offerId !== null && lastReport.get() === offerId) lastReport.clear();
    setView({
      kind: 'error',
      notFound,
      message: err instanceof Error && err.message ? err.message : 'The report could not be loaded.',
    });
  };

  const settle = useCallback(
    async (run: RunSnapshot) => {
      if (offerId === null) return;
      const runs = await api.getRuns(offerId);
      setHistory(runs);
      if (hasReport(run)) {
        lastReport.set(offerId);
        setView({ kind: 'report', run });
      } else {
        setView({ kind: 'failed', run, previous: runs.find(hasReport) ?? null });
      }
    },
    [offerId],
  );

  useEffect(() => {
    let cancelled = false;
    const stop = () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
    };

    if (offerId === null) {
      setView({ kind: 'error', notFound: true, message: `"${id ?? ''}" is not a valid report ID.` });
      return;
    }

    const poll = async (runId: string) => {
      try {
        const run = await api.getRun(offerId, runId);
        if (cancelled) return;
        if (isActive(run)) {
          setView({ kind: 'progress', run });
          timer.current = window.setTimeout(() => poll(runId), POLL_MS);
        } else {
          await settle(run);
        }
      } catch (err) {
        if (!cancelled) fail(err);
      }
    };

    const load = async () => {
      setView({ kind: 'loading' });
      try {
        api.getOffer(offerId).then((o) => !cancelled && setTitle(o.title)).catch(() => undefined);
        if (runParam) return poll(runParam);
        const runs = await api.getRuns(offerId);
        if (cancelled) return;
        setHistory(runs);
        const newest = runs[0];
        if (!newest) return setView({ kind: 'no-report' });
        if (isActive(newest)) return poll(newest.run_id);
        // GET /report reads the stored snapshot; it never starts a search.
        try {
          const report = await api.getReport(offerId);
          if (cancelled) return;
          if (newest.status === 'FAILED' && newest.version > report.version) {
            setView({ kind: 'failed', run: newest, previous: report });
          } else {
            lastReport.set(offerId);
            setView({ kind: 'report', run: report });
          }
        } catch (err) {
          if (err instanceof ApiError && err.isNoReport) {
            setView(newest.status === 'FAILED' ? { kind: 'failed', run: newest, previous: null } : { kind: 'no-report' });
          } else throw err;
        }
      } catch (err) {
        if (!cancelled) fail(err);
      }
    };

    window.scrollTo(0, 0);
    load();
    return () => {
      cancelled = true;
      stop();
    };
  }, [offerId, runParam, attempt, settle]);

  const runAgain = async (confirmed: ConfirmedClaim[]) => {
    if (offerId === null) return;
    setBusy(true);
    setActionError(null);
    try {
      const run = await api.startRun(offerId, confirmed, true);
      setParams({ run: run.run_id });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Could not start a new investigation.');
    } finally {
      setBusy(false);
    }
  };

  const deleteCase = async () => {
    if (offerId === null) return;
    if (!window.confirm('Delete this case permanently? The offer text and every report version will be removed.')) return;
    setBusy(true);
    try {
      await api.deleteOffer(offerId);
      if (lastReport.get() === offerId) lastReport.clear();
      navigate('/', { replace: true });
    } catch (err) {
      setBusy(false);
      setActionError(err instanceof Error ? err.message : 'Could not delete the case.');
    }
  };

  if (view.kind === 'loading') {
    return (
      <div className="py-20 text-center text-sm text-slate-500">
        <div className="w-10 h-10 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        Loading the report…
      </div>
    );
  }

  if (view.kind === 'error') {
    return (
      <div className="max-w-xl mx-auto py-20 text-center" role="alert">
        <div className="w-12 h-12 rounded-full bg-rose-50 border border-rose-200 text-rose-600 flex items-center justify-center mx-auto mb-4">
          <AlertTriangle className="w-6 h-6" />
        </div>
        <h1 className="text-xl font-bold text-slate-900">{view.notFound ? 'Report not found' : 'Report could not be loaded'}</h1>
        <p className="text-sm text-slate-600 mt-2">{view.message}</p>
        <div className="mt-6 flex items-center justify-center gap-3">
          {!view.notFound && (
            <button
              onClick={() => setAttempt((n) => n + 1)}
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white"
            >
              Try again
            </button>
          )}
          <Link to="/upload" className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white">
            Verify an offer
          </Link>
        </div>
      </div>
    );
  }

  if (view.kind === 'no-report') {
    return (
      <div className="max-w-xl mx-auto py-20 text-center">
        <h1 className="text-xl font-bold text-slate-900">No report yet</h1>
        <p className="text-sm text-slate-600 mt-2">This offer has not been investigated. Check its details and start the investigation.</p>
        <Link
          to={`/offers/${offerId}/review`}
          className="inline-block mt-6 px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white"
        >
          Review and investigate
        </Link>
      </div>
    );
  }

  if (view.kind === 'progress') {
    return (
      <div className="py-10">
        <RunProgress run={view.run} />
      </div>
    );
  }

  if (view.kind === 'failed') {
    return (
      <div className="max-w-xl mx-auto py-16 text-center" role="alert">
        <div className="w-12 h-12 rounded-full bg-rose-50 border border-rose-200 text-rose-600 flex items-center justify-center mx-auto mb-4">
          <AlertTriangle className="w-6 h-6" />
        </div>
        <h1 className="text-xl font-bold text-slate-900">The investigation did not finish</h1>
        <ul className="text-sm text-slate-600 mt-2 space-y-1">
          {view.run.errors.map((e, i) => (
            <li key={i}>{e.message}</li>
          ))}
        </ul>
        <p className="text-xs text-slate-500 mt-2">No verdict was produced, and none has been filled in for you.</p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => runAgain(view.previous?.report ? confirmationsFrom(view.previous.report) : [])}
            disabled={busy}
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white disabled:opacity-60"
          >
            Try again
          </button>
          <Link to={`/offers/${offerId}/review`} className="px-4 py-2 rounded-lg text-xs font-semibold border border-slate-300 text-slate-700">
            Review the details
          </Link>
          {view.previous && (
            <button
              onClick={() => setView({ kind: 'report', run: view.previous as RunSnapshot })}
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 text-white"
            >
              Show the previous report (version {view.previous.version})
            </button>
          )}
        </div>
        {actionError && <p className="mt-4 text-xs text-rose-700">{actionError}</p>}
      </div>
    );
  }

  const run = view.run;
  const result = run.report as InvestigationResult;
  const finished = history.filter(hasReport);
  const newer = history.find((r) => r.version > run.version && hasReport(r));

  const exportMarkdown = () =>
    downloadText(
      `aslioffer-report-${offerId}-v${run.version}.md`,
      buildMarkdownReport(result, { title, includeContacts, generatedAt: run.finished_at, version: run.version }),
    );

  const actions = (
    <>
      <button
        onClick={() => runAgain(confirmationsFrom(result))}
        disabled={busy}
        className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white inline-flex items-center gap-1.5 disabled:opacity-60"
      >
        <RefreshCw className="w-3.5 h-3.5" /> Run again with fresh searches
      </button>
      <button
        onClick={exportMarkdown}
        className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 text-slate-700 hover:bg-slate-50 inline-flex items-center gap-1.5"
      >
        <Download className="w-3.5 h-3.5" /> Download report
      </button>
      <label className="inline-flex items-center gap-1.5 text-xs text-slate-600 px-1">
        <input type="checkbox" checked={includeContacts} onChange={(e) => setIncludeContacts(e.target.checked)} />
        Include emails, phones and UPI IDs (for a cybercrime complaint)
      </label>
      <button
        onClick={() => window.print()}
        className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 text-slate-700 hover:bg-slate-50 inline-flex items-center gap-1.5"
      >
        <Printer className="w-3.5 h-3.5" /> Print / save PDF
      </button>
      <button
        onClick={deleteCase}
        disabled={busy}
        className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-rose-200 text-rose-700 hover:bg-rose-50 inline-flex items-center gap-1.5 disabled:opacity-60"
      >
        <Trash2 className="w-3.5 h-3.5" /> Delete case
      </button>
    </>
  );

  return (
    <div className="max-w-5xl mx-auto py-8 space-y-4 pb-20">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link to="/" className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-900">
          <ArrowLeft className="w-4 h-4" /> Back to Dashboard
        </Link>
        {finished.length > 1 && (
          <label className="text-xs text-slate-600 inline-flex items-center gap-2">
            Version
            <select
              value={run.run_id}
              onChange={(e) => {
                const picked = finished.find((r) => r.run_id === e.target.value);
                if (picked) setView({ kind: 'report', run: picked });
              }}
              className="border border-slate-300 rounded-lg px-2 py-1 text-xs"
            >
              {finished.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  v{r.version} · {formatTime(r.finished_at)}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {newer && (
        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
          You are viewing an older version. Version {newer.version} is newer.
        </p>
      )}
      {actionError && (
        <p role="alert" className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2">
          {actionError}
        </p>
      )}
      <InvestigationReport
        result={result}
        title={title}
        actions={actions}
        meta={
          <>
            CASE #{run.case_id} · VERSION {run.version} · {run.status === 'PARTIAL' ? 'PARTIAL · ' : ''}FINISHED{' '}
            {formatTime(run.finished_at)}
          </>
        }
      />
      <p className="text-[11px] text-slate-500 text-center">
        This case and its reports are deleted automatically 7 days after upload, or now with “Delete case”.
      </p>
    </div>
  );
};
