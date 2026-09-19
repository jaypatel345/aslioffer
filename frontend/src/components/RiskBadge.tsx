import React from 'react';
import { ShieldCheck, AlertTriangle, AlertCircle } from 'lucide-react';
import { RiskLevel } from '../types';

interface RiskBadgeProps {
  level: RiskLevel;
  score?: number;
  showScore?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export const RiskBadge: React.FC<RiskBadgeProps> = ({
  level,
  score,
  showScore = false,
  size = 'md',
}) => {
  const getBadgeConfig = () => {
    switch (level) {
      case 'VERIFIED':
        return {
          label: 'VERIFIED',
          icon: ShieldCheck,
          bg: 'bg-emerald-950/70',
          border: 'border-emerald-500/30',
          text: 'text-emerald-400',
          subtext: 'Matches verified corporate footprint',
          glow: 'shadow-[0_0_15px_rgba(16,185,129,0.2)]',
        };
      case 'NEEDS_REVIEW':
        return {
          label: 'NEEDS REVIEW',
          icon: AlertCircle,
          bg: 'bg-amber-950/70',
          border: 'border-amber-500/30',
          text: 'text-amber-400',
          subtext: 'Ambiguous credentials - manual check required',
          glow: 'shadow-[0_0_15px_rgba(245,158,11,0.2)]',
        };
      case 'HIGH_RISK':
      default:
        return {
          label: 'HIGH RISK',
          icon: AlertTriangle,
          bg: 'bg-rose-950/70',
          border: 'border-rose-500/30',
          text: 'text-rose-400',
          subtext: 'Severe scam indicators or advance fee detected',
          glow: 'shadow-[0_0_15px_rgba(244,63,94,0.25)]',
        };
    }
  };

  const config = getBadgeConfig();
  const Icon = config.icon;

  const sizeClasses = {
    sm: 'px-2 py-0.5 text-xs font-semibold',
    md: 'px-3 py-1.5 text-sm font-semibold',
    lg: 'px-4 py-2 text-base font-bold',
  };

  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border ${config.bg} ${config.border} ${config.text} ${config.glow} ${sizeClasses[size]}`}
      title={config.subtext}
    >
      <Icon className={size === 'lg' ? 'w-5 h-5' : size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'} />
      <span>{config.label}</span>
      {showScore && score !== undefined && (
        <span className="ml-1 px-1.5 py-0.5 rounded bg-black/40 text-xs font-mono">
          {(score * 100).toFixed(0)}% Risk
        </span>
      )}
    </div>
  );
};
