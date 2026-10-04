import React from 'react';
import { CheckCircle2, CircleDashed, MinusCircle, XCircle } from 'lucide-react';
import { EventStatus, RunSnapshot } from '../types';

const STEP_LABEL: Record<string, string> = {
  extract_claims: 'Reading the offer claims',
  resolve_company: 'Finding the employer’s official domain',
  check_recruiter: 'Checking the recruiter contact',
  check_compensation: 'Comparing compensation with public data',
  check_scam_signals: 'Checking the offer for scam signals',
  external_scam_search: 'Searching public scam warnings',
  plan_investigation: 'Planning follow-up checks',
  assess_verdict: 'Assessing each claim',
  run: 'Investigation',
};

const ICON: Record<EventStatus, React.ReactNode> = {
  STARTED: <CircleDashed className="w-4 h-4 text-emerald-600 animate-spin" />,
  COMPLETED: <CheckCircle2 className="w-4 h-4 text-emerald-600" />,
  SKIPPED: <MinusCircle className="w-4 h-4 text-slate-400" />,
  FAILED: <XCircle className="w-4 h-4 text-rose-600" />,
};

const label = (step: string) =>
  STEP_LABEL[step] ?? step.replace(/^adaptive_/, 'Follow-up: ').replace(/_/g, ' ');

/**
 * Progress built only from the events the investigator actually emitted.
 * Each step shows its latest status; nothing advances on a timer.
 */
export const RunProgress: React.FC<{ run: RunSnapshot }> = ({ run }) => {
  const latestByStep = new Map<string, { status: EventStatus; message: string; order: number }>();
  run.events.forEach((event, order) => {
    const first = latestByStep.get(event.step);
    latestByStep.set(event.step, {
      status: event.status,
      message: event.public_message,
      order: first ? first.order : order,
    });
  });
  const steps = [...latestByStep.entries()].sort((a, b) => a[1].order - b[1].order);
  const waiting = run.status === 'QUEUED';

  return (
    <div className="glass-panel rounded-2xl p-6 sm:p-8 max-w-xl mx-auto" aria-live="polite">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-8 h-8 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin shrink-0" />
        <div>
          <h2 className="text-lg font-bold text-slate-900">
            {waiting ? 'Investigation queued' : 'Investigating your offer'}
          </h2>
          <p className="text-xs text-slate-500">
            Version {run.version} · Steps appear as the investigator reports them. This usually takes under a minute.
          </p>
        </div>
      </div>

      {steps.length === 0 ? (
        <p className="text-sm text-slate-500">Waiting for the first step to start…</p>
      ) : (
        <ol className="space-y-2.5">
          {steps.map(([step, info]) => (
            <li key={step} className="flex items-start gap-3 text-sm">
              <span className="mt-0.5">{ICON[info.status]}</span>
              <span>
                <span className="font-semibold text-slate-800">{label(step)}</span>
                <span className="block text-xs text-slate-500">{info.message}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
};
