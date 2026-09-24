import React from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Building,
  UserCheck,
  IndianRupee,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react';
import { RiskBadge } from '../components/RiskBadge';

export const Dashboard: React.FC = () => {
  return (
    <div className="space-y-20 sm:space-y-28 pb-24">
      {/* Hero Section */}
      <section className="relative overflow-hidden pt-12 pb-6 text-center">
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-600 text-xs font-semibold mb-6">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>SerpApi India Hackathon 2026 • AI Agents Track</span>
        </div>

        <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-slate-900 max-w-4xl mx-auto leading-tight">
          Verify Job Offers With{' '}
          <span className="bg-clip-text text-transparent bg-gradient-to-r from-emerald-600 via-teal-500 to-cyan-600">
            Real Public Footprint Proof
          </span>
        </h1>

        <p className="mt-5 text-base sm:text-xl text-slate-600 max-w-2xl mx-auto leading-relaxed">
          Scammers can copy a corporate logo, but they cannot fake a company’s entire public footprint.
          Protect Indian freshers with automated multi-agent forensic verification.
        </p>

        <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
          <Link
            to="/upload"
            className="px-6 py-3.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold text-sm tracking-wide transition-all flex items-center gap-2"
          >
            <span>Verify an Offer Now</span>
            <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            to="/offers/101/report"
            className="px-6 py-3.5 rounded-xl bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-900 font-medium text-sm transition-colors flex items-center gap-2"
          >
            <span>View Sample Forensic Report</span>
            <ExternalLink className="w-3.5 h-3.5 text-slate-500" />
          </Link>
        </div>
      </section>

      {/* Core Insight Callout */}
      <section className="max-w-4xl mx-auto">
        <div className="glass-panel rounded-2xl p-6 sm:p-8 border-l-4 border-l-emerald-500">
          <h2 className="text-lg font-bold text-slate-900 mb-2">The AsliOffer Principle</h2>
          <blockquote className="text-slate-600 text-sm sm:text-base italic leading-relaxed">
            "A genuine job offer leaves a consistent trail across the internet — official domain MX records,
            Ministry of Corporate Affairs (MCA) registration, real careers pages, and realistic salary bands.
            A scam almost always breaks at least one."
          </blockquote>
        </div>
      </section>

      {/* Multi-Agent Architecture Visualization */}
      <section className="max-w-5xl mx-auto">
        <div className="text-center mb-10">
          <h2 className="text-2xl font-bold text-slate-900">Multi-Agent Investigation Pipeline</h2>
          <p className="text-sm text-slate-500 mt-1">
            Independent specialized agents query live SerpApi endpoints to cross-verify claims
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Company Agent */}
          <div className="glass-card rounded-xl p-5 border-t-2 border-t-blue-500">
            <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 mb-3">
              <Building className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Company Agent</h3>
            <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
              Audits corporate web footprint, registered MCA status, and verifies authentic careers portals.
            </p>
          </div>

          {/* Recruiter Agent */}
          <div className="glass-card rounded-xl p-5 border-t-2 border-t-purple-500">
            <div className="w-9 h-9 rounded-lg bg-purple-50 flex items-center justify-center text-purple-600 mb-3">
              <UserCheck className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Recruiter Agent</h3>
            <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
              Cross-references email domains (@company.com vs @gmail.com) and verifies recruiter identities.
            </p>
          </div>

          {/* Salary Agent */}
          <div className="glass-card rounded-xl p-5 border-t-2 border-t-emerald-500">
            <div className="w-9 h-9 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600 mb-3">
              <IndianRupee className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Salary Agent</h3>
            <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
              Compares stated CTC against AmbitionBox & Glassdoor market baselines to catch inflated bait offers.
            </p>
          </div>

          {/* Scam Agent */}
          <div className="glass-card rounded-xl p-5 border-t-2 border-t-rose-500">
            <div className="w-9 h-9 rounded-lg bg-rose-50 flex items-center justify-center text-rose-600 mb-3">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">Scam Agent</h3>
            <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">
              Detects illegal laptop/training deposits, UPI payment demands, and known CyberDost fraud signatures.
            </p>
          </div>
        </div>
      </section>

      {/* Case Studies / Recent Demo Offers */}
      <section className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-xl font-bold text-slate-900">Sample Offer Verifications</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Explore how AsliOffer categorizes genuine and fraudulent employment communications
            </p>
          </div>
          <Link
            to="/upload"
            className="text-xs font-semibold text-emerald-600 hover:text-emerald-700 flex items-center gap-1"
          >
            <span>Scan New Offer</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Card 1: Scam */}
          <div className="glass-card rounded-2xl p-6 border-slate-200 hover:border-slate-300 transition-all flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs text-slate-500 font-mono">ID #101 • PDF Offer</span>
                <RiskBadge level="HIGH_RISK" score={0.94} showScore />
              </div>
              <h3 className="text-base font-bold text-slate-900 mb-1">
                TCS Associate Software Engineer Offer
              </h3>
              <p className="text-xs text-slate-600 line-clamp-2">
                Contains demand for ₹15,000 laptop security deposit via UPI and was dispatched from a personal Gmail address.
              </p>
              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <span className="text-[10px] px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 font-mono">
                  UPI Fee Demanded
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 font-mono">
                  Personal Webmail
                </span>
              </div>
            </div>
            <div className="mt-5 pt-4 border-t border-slate-200/80 flex items-center justify-between">
              <span className="text-xs text-slate-500">4 Evidence Points</span>
              <Link
                to="/offers/101/report"
                className="text-xs font-semibold text-rose-600 hover:text-rose-700 flex items-center gap-1"
              >
                <span>View Full Audit</span>
                <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
          </div>

          {/* Card 2: Verified */}
          <div className="glass-card rounded-2xl p-6 border-slate-200 hover:border-slate-300 transition-all flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs text-slate-500 font-mono">ID #102 • Email Offer</span>
                <RiskBadge level="VERIFIED" score={0.12} showScore />
              </div>
              <h3 className="text-base font-bold text-slate-900 mb-1">
                Infosys Systems Engineer Specialist Offer
              </h3>
              <p className="text-xs text-slate-600 line-clamp-2">
                Dispatched from official domain @infosys.com, ₹6.25 LPA aligned with SES fresher bands, zero fee solicitation.
              </p>
              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-mono">
                  Corporate Domain
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-mono">
                  Zero Upfront Fee
                </span>
              </div>
            </div>
            <div className="mt-5 pt-4 border-t border-slate-200/80 flex items-center justify-between">
              <span className="text-xs text-slate-500">4 Evidence Points</span>
              <Link
                to="/offers/102/report"
                className="text-xs font-semibold text-emerald-600 hover:text-emerald-700 flex items-center gap-1"
              >
                <span>View Full Audit</span>
                <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};
