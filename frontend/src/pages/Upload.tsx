import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileUpload } from '../components/FileUpload';
import { api } from '../services/api';
import { lastReport } from '../services/lastReport';


export const Upload: React.FC = () => {
  const navigate = useNavigate();
  const [isProcessing, setIsProcessing] = useState(false);
  const [currentStep, setCurrentStep] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  const steps = [
    { title: 'Entity Extraction', desc: 'Parsing company, recruiter, compensation & fees' },
    { title: 'Company Footprint', desc: 'Querying SerpApi for domain & MCA corporate registry' },
    { title: 'Recruiter Domain Audit', desc: 'Verifying official mail server vs personal webmail' },
    { title: 'Salary Anomaly Check', desc: 'Comparing claimed CTC against AmbitionBox baselines' },
    { title: 'Scam Signature Search', desc: 'Auditing against advance fee fraud & CyberDost advisories' },
    { title: 'Report Synthesis', desc: 'Risk Engine assembling evidence citations' },
  ];

  const handleAnalyze = async (payload: { title: string; content: string; file?: File }) => {
    setIsProcessing(true);
    setCurrentStep(0);
    setError(null);

    // Simulate multi-agent sequential pipeline progression
    const stepInterval = setInterval(() => {
      setCurrentStep((prev) => {
        if (prev < steps.length - 1) {
          return prev + 1;
        }
        clearInterval(stepInterval);
        return prev;
      });
    }, 700);

    try {
      let offerId: number;
      if (payload.file) {
        const formData = new FormData();
        formData.append('title', payload.title);
        formData.append('file', payload.file);
        const res = await api.uploadOffer(formData);
        offerId = res.offer_id;
      } else {
        const res = await api.uploadOfferText(payload.title, payload.content);
        offerId = res.offer_id;
      }

      // Wait for agent pipeline animation
      setTimeout(() => {
        clearInterval(stepInterval);
        setIsProcessing(false);
        // Unlocks the "Report" link in the navbar — only a real investigation does.
        lastReport.set(offerId);
        navigate(`/offers/${offerId}/report`);
      }, 4200);
    } catch (err) {
      clearInterval(stepInterval);
      setIsProcessing(false);
      setError('Investigation could not be completed. Please check your connection and try again.');
    }
  };

  return (
    <div className="max-w-4xl mx-auto py-8">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-extrabold text-slate-900">
          Verify Job or Internship Offer
        </h1>
        <p className="text-sm text-slate-500 mt-2 max-w-xl mx-auto">
          Upload an offer letter (PDF/image) or paste an email/WhatsApp message.
          Our multi-agent system verifies the employer's public footprint in real-time.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700">
          {error}
        </div>
      )}

      <FileUpload onAnalyze={handleAnalyze} isLoading={isProcessing} />

      {/* Processing Animation Modal */}
      {isProcessing && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl p-6 sm:p-8 max-w-md w-full border border-emerald-300 shadow-2xl">
            <div className="text-center mb-6">
              <div className="w-12 h-12 rounded-full bg-emerald-50 border border-emerald-300 text-emerald-600 flex items-center justify-center mx-auto mb-3">
                <div className="w-6 h-6 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
              </div>
              <h3 className="text-lg font-bold text-slate-900">Investigating Live Public Footprint</h3>
              <p className="text-xs text-slate-500 mt-1">
                Querying live search endpoints with specialized AI agents
              </p>
            </div>

            <div className="space-y-3">
              {steps.map((step, idx) => {
                const isDone = idx < currentStep;
                const isCurrent = idx === currentStep;
                return (
                  <div
                    key={idx}
                    className={`flex items-start gap-3 p-2.5 rounded-xl text-xs transition-all ${
                      isCurrent
                        ? 'bg-emerald-50 border border-emerald-300 text-emerald-800'
                        : isDone
                        ? 'text-slate-500 opacity-80'
                        : 'text-slate-500 opacity-50'
                    }`}
                  >
                    <div className="mt-0.5">
                      {isDone ? (
                        <div className="w-4 h-4 rounded-full bg-emerald-600 text-white flex items-center justify-center text-[10px] font-bold">
                          ✓
                        </div>
                      ) : isCurrent ? (
                        <div className="w-4 h-4 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
                      ) : (
                        <div className="w-4 h-4 rounded-full border border-slate-300 flex items-center justify-center text-[10px]">
                          {idx + 1}
                        </div>
                      )}
                    </div>
                    <div>
                      <p className="font-semibold">{step.title}</p>
                      <p className="text-[11px] opacity-80">{step.desc}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
