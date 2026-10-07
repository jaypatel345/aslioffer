import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';
import { EventStatus, RunSnapshot } from '../types';

const STEP_LABEL: Record<string, string> = {
  extract_claims: 'Reading the offer claims',
  resolve_company: 'Finding the employer’s official domain',
  check_recruiter: 'Checking the recruiter contact',
  check_compensation: 'Comparing compensation with public data',
  check_compensation_benchmark: 'Looking up salary benchmarks',
  check_scam_signals: 'Checking the offer for scam signals',
  external_scam_search: 'Searching public scam warnings',
  plan_investigation: 'Planning follow-up checks',
  assess_verdict: 'Assessing each claim',
  run: 'Investigation',
};

// Every run emits these steps, so they are listed up front as "waiting" and the
// user can see what is still to come.
const EXPECTED_STEPS = [
  'extract_claims',
  'resolve_company',
  'check_recruiter',
  'check_scam_signals',
  'check_compensation',
  'plan_investigation',
  'assess_verdict',
];

// Skips that mean "nothing more was needed" rather than "this could not be checked".
const BENIGN_SKIPS = new Set(['plan_investigation']);

// Investigations can finish in milliseconds; each step is revealed at this pace so
// the user actually sees every check land, and the finished list stays up briefly.
const REVEAL_MS = 350;
const HOLD_MS = 2000;

type RowState = 'waiting' | 'running' | 'passed' | 'failed';

const label = (step: string) =>
  STEP_LABEL[step] ?? step.replace(/^adaptive_/, 'Follow-up: ').replace(/_/g, ' ');

function rowState(step: string, status: EventStatus | undefined, finished: boolean): RowState {
  if (status === 'COMPLETED') return 'passed';
  if (status === 'SKIPPED') return BENIGN_SKIPS.has(step) ? 'passed' : 'failed';
  if (status === 'FAILED') return 'failed';
  // A step still "started" or never reached once the run is over did not complete.
  if (finished) return 'failed';
  return status === 'STARTED' ? 'running' : 'waiting';
}

const ICON: Record<RowState, React.ReactNode> = {
  waiting: <Circle className="w-4 h-4 text-slate-300" />,
  running: <Loader2 className="w-4 h-4 text-emerald-600 animate-spin" />,
  passed: <CheckCircle2 className="w-4 h-4 text-emerald-600" />,
  failed: <XCircle className="w-4 h-4 text-rose-600" />,
};

const ROW_CLASS: Record<RowState, string> = {
  waiting: 'border-transparent',
  running: 'border-emerald-100 bg-emerald-50/40',
  passed: 'border-emerald-100 bg-emerald-50/60',
  failed: 'border-rose-200 bg-rose-50',
};

const TITLE_CLASS: Record<RowState, string> = {
  waiting: 'text-slate-400',
  running: 'text-slate-800',
  passed: 'text-emerald-900',
  failed: 'text-rose-700',
};

/**
 * Progress built only from the events the investigator actually emitted, shown
 * one at a time. Nothing advances on a timer except the pace at which real
 * events are revealed. When the run is over and every event has been shown,
 * `onFinished` is called after a short hold so the result can be read.
 */
export const RunProgress: React.FC<{ run: RunSnapshot; onFinished?: () => void }> = ({ run, onFinished }) => {
  const total = run.events.length;
  const [shown, setShown] = useState(0);
  const finishedCb = useRef(onFinished);
  finishedCb.current = onFinished;
  const fired = useRef(false);
  const finish = () => {
    if (fired.current || !finishedCb.current) return;
    fired.current = true;
    finishedCb.current();
  };

  const runOver = run.status !== 'QUEUED' && run.status !== 'RUNNING';
  const caughtUp = shown >= total;
  const done = runOver && caughtUp;

  useEffect(() => {
    if (caughtUp) return;
    const t = window.setTimeout(() => setShown((n) => n + 1), shown === 0 ? 0 : REVEAL_MS);
    return () => window.clearTimeout(t);
  }, [shown, caughtUp]);

  useEffect(() => {
    if (!done || !finishedCb.current) return;
    const t = window.setTimeout(finish, HOLD_MS);
    return () => window.clearTimeout(t);
  }, [done]);

  const latest = new Map<string, { status: EventStatus; message: string }>();
  const order: string[] = [];
  run.events.slice(0, shown).forEach((event) => {
    if (!latest.has(event.step)) order.push(event.step);
    latest.set(event.step, { status: event.status, message: event.public_message });
  });
  EXPECTED_STEPS.forEach((step) => {
    if (!latest.has(step)) order.push(step);
  });

  const rows = order.map((step) => {
    const info = latest.get(step);
    const state = rowState(step, info?.status, done);
    const message = info?.message ?? (done ? 'Not reached in this run' : 'Waiting…');
    return { step, state, message };
  });
  const passed = rows.filter((r) => r.state === 'passed').length;
  const failed = rows.filter((r) => r.state === 'failed').length;
  const settled = passed + failed;

  return (
    <div className="glass-panel rounded-xl p-6 sm:p-8 max-w-xl mx-auto" aria-live="polite">
      <div className="flex items-center gap-3 mb-5">
        {done ? (
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
              failed ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600'
            }`}
          >
            <CheckCircle2 className="w-5 h-5" />
          </div>
        ) : (
          <div className="w-8 h-8 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin shrink-0" />
        )}
        <div className="min-w-0">
          <h2 className="text-lg font-bold text-slate-900">
            {done ? 'Checks finished' : run.status === 'QUEUED' ? 'Investigation queued' : 'Investigating your offer'}
          </h2>
          <p className="text-xs text-slate-500">
            Version {run.version} ·{' '}
            {done
              ? `${passed} completed, ${failed} could not be confirmed. Opening your report…`
              : `${settled} of ${rows.length} steps done. This usually takes under a minute.`}
          </p>
        </div>
      </div>

      <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden mb-5" aria-hidden>
        <div
          className="h-full bg-emerald-500 transition-all duration-300"
          style={{ width: `${rows.length ? Math.round((settled / rows.length) * 100) : 0}%` }}
        />
      </div>

      <ol className="space-y-1.5">
        {rows.map(({ step, state, message }) => (
          <li
            key={step}
            data-state={state}
            className={`flex items-start gap-3 text-sm rounded-lg border px-3 py-2 transition-colors duration-300 ${ROW_CLASS[state]}`}
          >
            <span className="mt-0.5 shrink-0">{ICON[state]}</span>
            <span className="min-w-0">
              <span className={`font-semibold ${TITLE_CLASS[state]}`}>{label(step)}</span>
              <span className={`block text-xs ${state === 'failed' ? 'text-rose-600' : 'text-slate-500'}`}>{message}</span>
            </span>
          </li>
        ))}
      </ol>

      {done && onFinished && (
        <button
          onClick={finish}
          className="mt-5 w-full px-4 py-2 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white inline-flex items-center justify-center gap-1.5"
        >
          View report now <ArrowRight className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
};
