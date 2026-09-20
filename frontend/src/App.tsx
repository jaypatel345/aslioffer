import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Navbar } from './components/Navbar';
import { Dashboard } from './pages/Dashboard';
import { Upload } from './pages/Upload';
import { OfferReport } from './pages/OfferReport';
import { ShieldCheck, PhoneCall, ExternalLink } from 'lucide-react';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100 selection:bg-emerald-500 selection:text-slate-950">
        <Navbar />

        <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 pt-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/upload" element={<Upload />} />
            <Route path="/offers/:id/report" element={<OfferReport />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>

        {/* Footer */}
        <footer className="border-t border-slate-900 bg-slate-950/90 py-8 mt-12 text-xs text-slate-500">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span className="font-semibold text-slate-300">AsliOffer</span>
              <span>— Evidence-Backed Job Offer Verification</span>
            </div>

            <div className="flex items-center gap-6">
              <a
                href="https://cybercrime.gov.in"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-slate-300 flex items-center gap-1 transition-colors"
              >
                <span>National Cyber Crime Portal</span>
                <ExternalLink className="w-3 h-3" />
              </a>
              <span className="flex items-center gap-1 text-rose-400 font-medium">
                <PhoneCall className="w-3 h-3" />
                <span>Helpline: 1930</span>
              </span>
            </div>

            <div>
              Built for <strong className="text-slate-400">SerpApi India Hackathon 2026</strong> (AI Agents Track)
            </div>
          </div>
        </footer>
      </div>
    </BrowserRouter>
  );
};

export default App;
