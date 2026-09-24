import React, { useSyncExternalStore } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Shield, CheckCircle2 } from 'lucide-react';
import { lastReport } from '../services/lastReport';

export const Navbar: React.FC = () => {
  const location = useLocation();
  const lastReportId = useSyncExternalStore(lastReport.subscribe, lastReport.get);

  const isActive = (path: string) => location.pathname === path;

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200/80 bg-white/85 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <Link to="/" className="flex items-center gap-3 group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-500 flex items-center justify-center group-hover:scale-105 transition-transform">
            <Shield className="w-5 h-5 text-white font-bold" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl font-extrabold tracking-tight text-slate-900">
                Asli<span className="text-emerald-600">Offer</span>
              </span>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 hidden sm:inline-block">
                MVP 0.1
              </span>
            </div>
            <p className="text-[10px] text-slate-500 tracking-wide hidden sm:block">
              Evidence-Backed Job Offer Verification
            </p>
          </div>
        </Link>

        {/* Navigation */}
        <nav className="flex items-center gap-1 sm:gap-3">
          <Link
            to="/"
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              isActive('/')
                ? 'bg-gray-100 text-gray-700 border border-gray-300'
                : 'text-gray-700 hover:bg-gray-50'
            }`}
          >
            Dashboard
          </Link>
          <Link
            to="/upload"
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5 ${
              isActive('/upload')
                ? 'bg-gray-100 text-gray-700 border border-gray-300'
                : 'text-gray-700 hover:bg-gray-50'
            }`}
          >
            <span>Verify Offer</span>
          </Link>
          {lastReportId !== null && (
            <Link
              to={`/offers/${lastReportId}/report`}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors hidden md:flex items-center ${
                location.pathname.includes('/report')
                  ? 'bg-gray-100 text-gray-700 border border-gray-300'
                  : 'text-gray-700 hover:bg-gray-50'
              }`}
            >
              <span>Report</span>
            </Link>
          )}
        </nav>

        {/* Track Badge */}
        <div className="hidden lg:flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 bg-slate-50/90 px-3 py-1.5 rounded-full border border-slate-200">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
            <span>SerpApi India Hackathon 2026</span>
          </div>
        </div>
      </div>
    </header>
  );
};
