import React from 'react';
import { ExternalLink, CheckCircle, AlertOctagon, Info } from 'lucide-react';
import { EvidenceItem } from '../types';

interface EvidenceCardProps {
  evidence: EvidenceItem;
}

export const EvidenceCard: React.FC<EvidenceCardProps> = ({ evidence }) => {
  const getTypeColor = (type: string) => {
    switch (type.toUpperCase()) {
      case 'COMPANY':
        return 'bg-blue-50 text-blue-600 border-blue-300';
      case 'RECRUITER':
        return 'bg-purple-50 text-purple-600 border-purple-300';
      case 'SALARY':
        return 'bg-emerald-50 text-emerald-600 border-emerald-300';
      case 'SCAM_REPORT':
        return 'bg-rose-50 text-rose-600 border-rose-300';
      default:
        return 'bg-slate-100 text-slate-600 border-slate-300';
    }
  };

  const getStatusIcon = (type: string) => {
    if (type.toUpperCase() === 'SCAM_REPORT') {
      return <AlertOctagon className="w-4 h-4 text-rose-600 shrink-0" />;
    }
    if (evidence.confidence >= 0.85) {
      return <CheckCircle className="w-4 h-4 text-emerald-600 shrink-0" />;
    }
    return <Info className="w-4 h-4 text-amber-600 shrink-0" />;
  };

  return (
    <div className="glass-card rounded-xl p-4 transition-all duration-200 hover:border-slate-400 hover:bg-slate-100/80">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={`text-xs px-2.5 py-0.5 rounded-full border font-medium uppercase tracking-wider ${getTypeColor(
              evidence.evidence_type
            )}`}
          >
            {evidence.evidence_type}
          </span>
          <span className="text-xs text-slate-500 font-mono">
            {(evidence.confidence * 100).toFixed(0)}% Confidence
          </span>
        </div>

        {evidence.source_url && (
          <a
            href={evidence.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-emerald-600 hover:text-emerald-700 font-medium transition-colors"
          >
            <span>Live Source</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>

      <div className="flex items-start gap-2.5 mt-1">
        <div className="mt-0.5">{getStatusIcon(evidence.evidence_type)}</div>
        <div>
          <h4 className="text-sm font-semibold text-slate-900">{evidence.title}</h4>
          <p className="text-xs text-slate-600 mt-1 leading-relaxed">
            {evidence.description}
          </p>
        </div>
      </div>
    </div>
  );
};
