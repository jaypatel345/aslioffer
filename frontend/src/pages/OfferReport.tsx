import React, { useEffect, useState } from 'react';
import { useParams, useLocation, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Building2,
  PhoneCall,
  ExternalLink,
  AlertTriangle,
  CheckCircle2,
  FileCheck,
  Shield,
  Clock,
  Printer,
} from 'lucide-react';
import { api, ApiError } from '../services/api';
import { lastReport } from '../services/lastReport';
import { VerificationReport } from '../types';
import { RiskBadge } from '../components/RiskBadge';
import { EntityPanel } from '../components/EntityPanel';
import { EvidenceCard } from '../components/EvidenceCard';

interface OfferReportProps {
  /** Render a built-in illustrative sample instead of fetching a case. */
  sample?: { label: string; report: VerificationReport };
}

type LoadError = { notFound: boolean; message: string };

export const OfferReport: React.FC<OfferReportProps> = ({ sample }) => {
  const { id } = useParams<{ id: string }>();
  // No default ID: a missing or malformed ID is an error, not a sample case.
  const parsedId = Number(id);
  const offerId = Number.isInteger(parsedId) && parsedId > 0 ? parsedId : null;
  const location = useLocation();
  // Handed over by the upload page, which already ran the agents.
  const preloaded = (location.state as { report?: VerificationReport } | null)?.report;
  const [report, setReport] = useState<VerificationReport | null>(sample?.report ?? null);
  const [loading, setLoading] = useState(!sample);
  const [error, setError] = useState<LoadError | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let isMounted = true;

    // Arriving from the upload form, which the user had scrolled down to submit.
    window.scrollTo(0, 0);

    if (sample) {
      setReport(sample.report);
      setError(null);
      setLoading(false);
      return;
    }

    if (offerId === null) {
      setReport(null);
      setError({ notFound: true, message: `"${id ?? ''}" is not a valid report ID.` });
      setLoading(false);
      return;
    }

    if (preloaded && preloaded.offer_id === offerId && attempt === 0) {
      setReport(preloaded);
      setError(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    setReport(null);

    api
      .getOfferReport(offerId)
      .then((data) => {
        if (isMounted) {
          setReport(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        const notFound = err instanceof ApiError && err.isNotFound;
        // The navbar's "Report" link points at a case the backend no longer has.
        if (notFound && lastReport.get() === offerId) lastReport.clear();
        setError({
          notFound,
          message: notFound
            ? `No offer with ID ${offerId} exists. The link may be wrong, or the case was removed.`
            : err instanceof Error && err.message
            ? err.message
            : 'The report could not be loaded.',
        });
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [offerId, sample, attempt]);

  if (error) {
    return (
      <div className="max-w-xl mx-auto py-20 text-center" role="alert">
        <div className="w-12 h-12 rounded-full bg-rose-50 border border-rose-200 text-rose-600 flex items-center justify-center mx-auto mb-4">
          <AlertTriangle className="w-6 h-6" />
        </div>
        <h1 className="text-xl font-bold text-slate-900">
          {error.notFound ? 'Report not found' : 'Report could not be loaded'}
        </h1>
        <p className="text-sm text-slate-600 mt-2">{error.message}</p>
        <div className="mt-6 flex items-center justify-center gap-3">
          {!error.notFound && (
            <button
              onClick={() => setAttempt((n) => n + 1)}
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-white transition-colors"
            >
              Try again
            </button>
          )}
          <Link
            to="/upload"
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white transition-colors"
          >
            Verify an offer
          </Link>
        </div>
      </div>
    );
  }

  if (loading || !report) {
    return (
      <div className="max-w-4xl mx-auto py-20 text-center">
        <div className="w-10 h-10 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-slate-500 text-sm">Compiling forensic evidence audit...</p>
      </div>
    );
  }

  const isHighRisk = report.risk_level === 'HIGH_RISK';
  const isVerified = report.risk_level === 'VERIFIED';
  const isCannotVerify = report.risk_level === 'CANNOT_VERIFY';

  return (
    <div className="max-w-5xl mx-auto py-8 space-y-8 pb-20">
      {/* Top Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Dashboard</span>
        </Link>
        <div className="flex items-center gap-3">
          <button
            onClick={() => window.print()}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-50 hover:bg-slate-100 text-slate-600 border border-slate-200 transition-colors flex items-center gap-1.5"
          >
            <Printer className="w-3.5 h-3.5" />
            <span>Save Report</span>
          </button>
          <Link
            to="/upload"
            className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white transition-colors"
          >
            Scan Another Offer
          </Link>
        </div>
      </div>

      {sample && (
        <div
          role="note"
          className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900"
        >
          <strong className="font-semibold">Illustrative sample — {sample.label}.</strong> This report was written by
          hand to show the report layout. It is not the result of a live investigation, and its sources were not
          retrieved for you. <Link to="/upload" className="underline font-semibold">Verify a real offer</Link>.
        </div>
      )}

      {/* Header Banner */}
      <div
        className={`glass-panel rounded-2xl p-6 sm:p-8 border-l-4 ${
          isHighRisk
            ? 'border-l-rose-500 glow-rose'
            : isVerified
            ? 'border-l-emerald-500 glow-emerald'
            : isCannotVerify
            ? 'border-l-slate-400 bg-slate-50/40'
            : 'border-l-amber-500 glow-amber'
        }`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <div>
            <div className="flex items-center gap-2 text-xs text-slate-500 font-mono mb-1">
              <span>{sample ? 'ILLUSTRATIVE SAMPLE' : `REPORT #${report.offer_id}`}</span>
              <span>•</span>
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {new Date(report.generated_at).toLocaleString()}
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
              {report.title}
            </h1>
          </div>
          <RiskBadge level={report.risk_level} score={report.risk_score} showScore size="lg" />
        </div>

        <p className="text-sm sm:text-base text-slate-700 leading-relaxed bg-slate-50/60 p-4 rounded-xl border border-slate-200">
          {report.summary}
        </p>

        {report.reason_details && report.reason_details.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {report.reason_details.map((rd, i) => (
              <span
                key={i}
                className="text-[11px] font-mono px-2.5 py-1 rounded-lg bg-slate-50/90 border border-slate-300 text-slate-600"
              >
                <strong className="text-emerald-600">{rd.code}</strong> — {rd.reason}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Flags Section (Red vs Green) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Red Flags */}
        <div className="glass-panel rounded-2xl p-6 border-slate-200">
          <h3 className="text-base font-bold text-rose-600 flex items-center gap-2 mb-4">
            <AlertTriangle className="w-5 h-5" />
            <span>Critical Red Flags ({report.red_flags.length})</span>
          </h3>
          {report.red_flags.length > 0 ? (
            <ul className="space-y-2.5">
              {report.red_flags.map((flag, idx) => (
                <li
                  key={idx}
                  className="flex items-start gap-2.5 text-xs text-rose-800 bg-rose-50 p-3 rounded-xl border border-rose-200 leading-relaxed"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-400 mt-1.5 shrink-0" />
                  <span>{flag}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-slate-500 italic">No red flags identified in this offer.</p>
          )}
        </div>

        {/* Green Flags */}
        <div className="glass-panel rounded-2xl p-6 border-slate-200">
          <h3 className="text-base font-bold text-emerald-600 flex items-center gap-2 mb-4">
            <CheckCircle2 className="w-5 h-5" />
            <span>Verified Green Flags ({report.green_flags.length})</span>
          </h3>
          {report.green_flags.length > 0 ? (
            <ul className="space-y-2.5">
              {report.green_flags.map((flag, idx) => (
                <li
                  key={idx}
                  className="flex items-start gap-2.5 text-xs text-emerald-800 bg-emerald-50 p-3 rounded-xl border border-emerald-200 leading-relaxed"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mt-1.5 shrink-0" />
                  <span>{flag}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-slate-500 italic">No green flags verified.</p>
          )}
        </div>
      </div>

      {/* Extracted Entities */}
      <EntityPanel entities={report.extracted_entities} />

      {/* Agent Investigation Breakdown */}
      <div className="glass-panel rounded-2xl p-6 sm:p-8 space-y-6">
        <div className="flex items-center justify-between pb-4 border-b border-slate-200">
          <div>
            <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
              <Shield className="w-5 h-5 text-emerald-600" />
              <span>Multi-Agent Investigation Evidence</span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Live SerpApi public search citations and cross-checked registries
            </p>
          </div>
          <span className="text-xs font-mono px-2.5 py-1 rounded bg-slate-100 text-slate-600 border border-slate-300">
            {report.findings.length} Agents Completed
          </span>
        </div>

        <div className="space-y-6">
          {report.findings.map((finding, idx) => (
            <div key={idx} className="p-5 rounded-xl bg-slate-50/80 border border-slate-200">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <div className="flex items-center gap-2.5">
                  <h4 className="text-sm font-bold text-slate-900">{finding.agent_name}</h4>
                  <span
                    className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                      finding.verdict === 'VERIFIED'
                        ? 'bg-emerald-50 text-emerald-600 border border-emerald-200'
                        : finding.verdict === 'HIGH_RISK'
                        ? 'bg-rose-50 text-rose-600 border border-rose-200'
                        : 'bg-amber-50 text-amber-600 border border-amber-200'
                    }`}
                  >
                    {finding.verdict}
                  </span>
                </div>
                <span className="text-xs text-slate-500 font-mono">
                  {(finding.confidence * 100).toFixed(0)}% Confidence
                </span>
              </div>

              <p className="text-xs text-slate-600 mb-4 leading-relaxed">
                {finding.summary}
              </p>

              {/* Evidence Cards */}
              {finding.evidence && finding.evidence.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
                  {finding.evidence.map((ev, evIdx) => (
                    <EvidenceCard key={evIdx} evidence={ev} />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Official Company Footprint & Verification Contact */}
      <div className="glass-panel rounded-2xl p-6 sm:p-8">
        <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-2">
          <Building2 className="w-5 h-5 text-blue-600" />
          <span>Official Employer Public Footprint</span>
        </h3>
        <p className="text-xs text-slate-500 mb-5">
          Always confirm recruitment details through the genuine corporate portal, not numbers provided in chat.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 min-w-0">
            <span className="text-xs text-slate-500 block mb-1">Company Website</span>
            <a
              href={report.official_company_info.website || '#'}
              target="_blank"
              rel="noopener noreferrer"
              title={report.official_company_info.website || undefined}
              className="text-sm font-semibold text-emerald-600 hover:underline flex items-center gap-1 min-w-0"
            >
              <span className="truncate">{report.official_company_info.website || 'Not available'}</span>
              <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 min-w-0">
            <span className="text-xs text-slate-500 block mb-1">Official Careers Page</span>
            <a
              href={report.official_company_info.careers_url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              title={report.official_company_info.careers_url || undefined}
              className="text-sm font-semibold text-emerald-600 hover:underline flex items-center gap-1 min-w-0"
            >
              <span className="truncate">{report.official_company_info.careers_url || 'Not available'}</span>
              <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200">
            <span className="text-xs text-slate-500 block mb-1">Corporate Registration</span>
            <p className="text-sm font-semibold text-slate-700">
              {report.official_company_info.mca_status || 'Not checked'}
            </p>
          </div>
        </div>

        {report.official_company_info.recruitment_policy && (
          <div className="mt-4 p-3 rounded-xl bg-slate-50/60 border border-slate-200 text-xs text-slate-500">
            <strong className="text-slate-600">Policy: </strong>
            {report.official_company_info.recruitment_policy}
          </div>
        )}
      </div>

      {/* Actionable Next Steps & CyberCrime Helpline */}
      <div
        className={`glass-panel rounded-2xl p-6 sm:p-8 ${
          isHighRisk ? 'border-rose-200 bg-rose-50' : 'border-slate-200'
        }`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <FileCheck className="w-5 h-5 text-emerald-600" />
            <span>Recommended Next Steps</span>
          </h3>

          {isHighRisk && (
            <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-rose-50 text-rose-700 border border-rose-300 text-xs font-bold">
              <PhoneCall className="w-3.5 h-3.5" />
              <span>National Cyber Helpline: 1930</span>
            </div>
          )}
        </div>

        <ul className="space-y-2.5">
          {report.recommended_actions.map((action, idx) => (
            <li
              key={idx}
              className="flex items-start gap-2.5 text-xs sm:text-sm text-slate-700 leading-relaxed"
            >
              <span className="w-5 h-5 rounded-full bg-slate-100 flex items-center justify-center text-xs font-semibold text-emerald-600 shrink-0 mt-0.5">
                {idx + 1}
              </span>
              <span>{action}</span>
            </li>
          ))}
        </ul>

        {isHighRisk && (
          <div className="mt-6 pt-5 border-t border-rose-200 flex flex-wrap items-center justify-between gap-4">
            <div className="text-xs text-rose-700">
              Reported fraud helps safeguard thousands of vulnerable freshers across India.
            </div>
            <a
              href="https://cybercrime.gov.in"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold transition-colors inline-flex items-center gap-1.5"
            >
              <span>File NCRP Report (cybercrime.gov.in)</span>
              <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        )}
      </div>
    </div>
  );
};
