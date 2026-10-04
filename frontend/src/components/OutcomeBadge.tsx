import React from 'react';
import { AlertTriangle, AlertCircle, HelpCircle, ShieldCheck } from 'lucide-react';
import { OverallOutcome } from '../types';
import { OUTCOME, TONE_CLASSES } from '../report/labels';

const ICONS: Record<OverallOutcome, React.ElementType> = {
  HIGH_RISK: AlertTriangle,
  NEEDS_REVIEW: AlertCircle,
  CANNOT_VERIFY: HelpCircle,
  NO_STRONG_RISK_SIGNALS: ShieldCheck,
};

/** Outcome label only. There is deliberately no score or percentage: none is calibrated. */
export const OutcomeBadge: React.FC<{ outcome: OverallOutcome; size?: 'sm' | 'lg' }> = ({ outcome, size = 'sm' }) => {
  const config = OUTCOME[outcome];
  const Icon = ICONS[outcome];
  const tone = TONE_CLASSES[config.tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold ${tone.chip} ${
        size === 'lg' ? 'px-4 py-2 text-sm' : 'px-2.5 py-1 text-xs'
      }`}
    >
      <Icon className={size === 'lg' ? 'w-4 h-4' : 'w-3.5 h-3.5'} />
      {config.label}
    </span>
  );
};
