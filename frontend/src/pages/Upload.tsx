import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileUpload } from '../components/FileUpload';
import { api } from '../services/api';

export const Upload: React.FC = () => {
  const navigate = useNavigate();
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = async (payload: { title: string; content: string; file?: File; sample?: boolean }) => {
    setIsProcessing(true);
    setError(null);
    try {
      let offerId: number;
      if (payload.file) {
        const formData = new FormData();
        formData.append('title', payload.title);
        formData.append('file', payload.file);
        offerId = (await api.uploadOffer(formData)).offer_id;
      } else {
        offerId = (await api.uploadOfferText(payload.title, payload.content, payload.sample ?? false)).offer_id;
      }
      // Nothing is searched yet: the user checks the extracted details first.
      navigate(`/offers/${offerId}/review`);
    } catch (err) {
      setIsProcessing(false);
      setError(err instanceof Error && err.message ? err.message : 'The offer could not be uploaded. Please try again.');
    }
  };

  return (
    <div className="max-w-3xl mx-auto py-10 sm:py-14">
      <div className="mb-8 text-center">
        <p className="text-xs font-semibold text-emerald-600 uppercase tracking-wider">Step 1 of 3 · Add your offer</p>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 mt-2">Verify a Job or Internship Offer</h1>
        <p className="text-sm text-slate-500 mt-2 max-w-xl mx-auto">
          Upload an offer letter (PDF or image) or paste an email or WhatsApp message. You will check the details we read
          before anything is searched.
        </p>
        <p className="text-xs text-slate-500 mt-2 max-w-xl mx-auto">
          Your case can only be opened from this browser and is deleted automatically after 7 days. You can delete it
          sooner from the report.
        </p>
      </div>

      {error && (
        <div role="alert" className="mb-4 p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700">
          {error}
        </div>
      )}

      <FileUpload onAnalyze={handleAnalyze} isLoading={isProcessing} />
    </div>
  );
};
