import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Shield, Search, FileText, CheckCircle2 } from 'lucide-react';

export const Navbar: React.FC = () => {
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-800/80 bg-slate-950/85 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <Link to="/" className="flex items-center gap-3 group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-400 flex items-center justify-center shadow-lg shadow-emerald-950/50 group-hover:scale-105 transition-transform">
            <Shield className="w-5 h-5 text-slate-950 font-bold" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl font-extrabold tracking-tight text-white">
                Asli<span className="text-emerald-400">Offer</span>
              </span>
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-800/60 hidden sm:inline-block">
                MVP 0.1
              </span>
            </div>
            <p className="text-[10px] text-slate-400 tracking-wide hidden sm:block">
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
                ? 'bg-slate-800 text-white border border-slate-700'
                : 'text-slate-300 hover:text-white hover:bg-slate-900'
            }`}
          >
            Dashboard
          </Link>
          <Link
            to="/upload"
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5 ${
              isActive('/upload')
                ? 'bg-emerald-600 text-slate-950 font-semibold shadow-sm'
                : 'text-emerald-400 hover:bg-emerald-950/40 border border-emerald-900/60'
            }`}
          >
            <Search className="w-3.5 h-3.5" />
            <span>Verify Offer</span>
          </Link>
          <Link
            to="/offers/101/report"
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors hidden md:flex items-center gap-1.5 ${
              location.pathname.includes('/report')
                ? 'bg-slate-800 text-white border border-slate-700'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Sample Report</span>
          </Link>
        </nav>

        {/* Track Badge */}
        <div className="hidden lg:flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-slate-400 bg-slate-900/90 px-3 py-1.5 rounded-full border border-slate-800">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span>SerpApi India Hackathon 2026</span>
          </div>
        </div>
      </div>
    </header>
  );
};
