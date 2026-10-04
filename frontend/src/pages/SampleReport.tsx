import React from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { ArrowLeft, Download } from 'lucide-react';
import { SAMPLE_REPORTS } from '../samples/sampleReports';
import { InvestigationReport } from '../components/InvestigationReport';
import { buildMarkdownReport, downloadText } from '../report/exportReport';

/** Explicit, clearly bannered sample report. The only place sample data is shown. */
export const SampleReport: React.FC = () => {
  const { key } = useParams<{ key: string }>();
  const entry = key ? SAMPLE_REPORTS[key] : undefined;
  if (!entry) return <Navigate to="/" replace />;

  return (
    <div className="max-w-5xl mx-auto py-8 space-y-4 pb-20">
      <Link to="/" className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-900 print:hidden">
        <ArrowLeft className="w-4 h-4" /> Back to Dashboard
      </Link>
      <div role="note" className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        <strong className="font-semibold">Illustrative sample — {entry.label}.</strong> Built from synthetic example data to
        show the report layout. It is not a live investigation, and its companies, people and links are made up.{' '}
        <Link to="/upload" className="underline font-semibold">
          Verify a real offer
        </Link>
        .
      </div>
      <InvestigationReport
        key={entry.key}
        result={entry.result}
        title={entry.title}
        meta="ILLUSTRATIVE SAMPLE · SYNTHETIC DATA"
        actions={
          <button
            onClick={() =>
              downloadText(
                `aslioffer-sample-${entry.key}.md`,
                buildMarkdownReport(entry.result, { title: entry.title, includeContacts: false, sample: true }),
              )
            }
            className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 text-slate-700 hover:bg-slate-50 inline-flex items-center gap-1.5"
          >
            <Download className="w-3.5 h-3.5" /> Download sample report
          </button>
        }
      />
    </div>
  );
};
