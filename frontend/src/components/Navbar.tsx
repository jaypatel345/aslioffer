import React, { useSyncExternalStore } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Shield, ArrowRight } from 'lucide-react';
import { lastReport } from '../services/lastReport';

export const Navbar: React.FC = () => {
  const location = useLocation();
  const lastReportId = useSyncExternalStore(lastReport.subscribe, lastReport.get);

  const linkClass = (active: boolean) =>
    `px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
      active ? 'text-slate-900 bg-slate-100' : 'text-slate-500 hover:text-slate-900'
    }`;

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200/70 bg-white/80 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between gap-4">
        {/* Brand */}
        <Link to="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-slate-900 flex items-center justify-center">
            <Shield className="w-4 h-4 text-emerald-400" />
          </div>
          <span className="text-base font-bold tracking-tight text-slate-900">
            Asli<span className="text-emerald-600">Offer</span>
          </span>
        </Link>

        {/* Navigation */}
        <nav className="flex items-center gap-1">
          <Link to="/" className={linkClass(location.pathname === '/')}>
            Home
          </Link>
          {lastReportId !== null && (
            <Link
              to={`/offers/${lastReportId}/report`}
              className={`${linkClass(location.pathname.includes('/report'))} hidden sm:inline-flex`}
            >
              Last report
            </Link>
          )}
          <Link
            to="/upload"
            className="ml-2 inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-sm font-medium transition-colors"
          >
            <span>Verify offer</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </nav>
      </div>
    </header>
  );
};
