import React, { useState, useRef } from 'react';
import { Upload, FileText, Sparkles, AlertCircle, Check } from 'lucide-react';

interface FileUploadProps {
  onAnalyze: (payload: { title: string; content: string; file?: File; demoId?: number }) => void;
  isLoading: boolean;
}

export const FileUpload: React.FC<FileUploadProps> = ({ onAnalyze, isLoading }) => {
  const [activeTab, setActiveTab] = useState<'text' | 'file'>('text');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const sampleScamText = `Offer Letter - Tata Consultancy Services
Candidate Name: Arjun Mehta
Role: Associate Software Engineer
Location: Bengaluru / Remote
CTC: INR 8.5 LPA

Dear Arjun,
Congratulations! Your profile has been shortlisted. We are pleased to extend this offer. 
To complete onboarding and dispatch your company laptop and training kit, kindly deposit a refundable security deposit of INR 15,000 via UPI to tcs-recruiter@upi. 

This amount will be refunded in your first month's salary. Send screenshot to HR at rohit.tcs.hiring@gmail.com or on Telegram @tcs_onboarding.`;

  const sampleLegitText = `Employment Offer - Infosys Limited
Candidate Name: Priyanka Sharma
Designation: Systems Engineer Specialist
Location: Electronics City, Bengaluru
CTC: INR 6,25,000 per annum (Plus standard medical insurance and retiral benefits)

Dear Priyanka,
With reference to your campus interview and subsequent discussions, Infosys Limited is pleased to make you an offer of employment.
Please review the attached terms. Report to the Bangalore Development Center on July 14, 2026.
Infosys does not request any fees, deposits, or payments from candidates at any stage.
For queries, contact your recruitment coordinator at pooja.kulkarni@infosys.com.`;

  const handlePresetScam = () => {
    setTitle('TCS Associate Software Engineer Offer Letter');
    setContent(sampleScamText);
    setSelectedFile(null);
    setActiveTab('text');
  };

  const handlePresetLegit = () => {
    setTitle('Infosys Systems Engineer Specialist Offer');
    setContent(sampleLegitText);
    setSelectedFile(null);
    setActiveTab('text');
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      setSelectedFile(file);
      if (!title) setTitle(file.name.replace(/\.[^/.]+$/, ''));
      setActiveTab('file');
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setSelectedFile(file);
      if (!title) setTitle(file.name.replace(/\.[^/.]+$/, ''));
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (activeTab === 'file' && selectedFile) {
      onAnalyze({
        title: title || selectedFile.name,
        content: `File upload: ${selectedFile.name}`,
        file: selectedFile,
      });
    } else {
      if (!content.trim()) return;
      onAnalyze({
        title: title || 'Pasted Job Offer Message',
        content,
      });
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-6 sm:p-8">
      {/* Quick Presets */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3 pb-5 border-b border-slate-200">
        <div>
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">
            Quick Test Scenarios
          </span>
          <p className="text-xs text-slate-500">Load test cases to see real-time agent verification</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handlePresetScam}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 transition-colors flex items-center gap-1.5"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>Load Scam Pattern (TCS + UPI Fee)</span>
          </button>
          <button
            type="button"
            onClick={handlePresetLegit}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-200 transition-colors flex items-center gap-1.5"
          >
            <Check className="w-3.5 h-3.5" />
            <span>Load Verified Pattern (Infosys)</span>
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex rounded-xl bg-slate-50/80 p-1 mb-6 border border-slate-200 max-w-md">
        <button
          type="button"
          onClick={() => setActiveTab('text')}
          className={`flex-1 py-2 text-xs sm:text-sm font-medium rounded-lg transition-all ${
            activeTab === 'text'
              ? 'bg-slate-100 text-slate-900 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          Paste Message / Email Text
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('file')}
          className={`flex-1 py-2 text-xs sm:text-sm font-medium rounded-lg transition-all ${
            activeTab === 'file'
              ? 'bg-slate-100 text-slate-900 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          Upload PDF / Screenshot
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-xs font-semibold text-slate-600 mb-1.5">
            Offer Title or Company Name
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. TCS Graduate Trainee Offer Letter"
            className="w-full px-4 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-900 placeholder-slate-500 focus:outline-none focus:border-emerald-500 transition-colors"
          />
        </div>

        {activeTab === 'text' ? (
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-xs font-semibold text-slate-600">
                Offer Letter or Recruiter Message Text
              </label>
              <span className="text-xs text-slate-500 font-mono">
                {content.length} characters
              </span>
            </div>
            <textarea
              rows={14}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Paste the full email, WhatsApp message, Telegram chat, or offer letter text here..."
              className="w-full px-4 py-4 rounded-xl bg-slate-50 border border-slate-200 text-sm text-slate-900 placeholder-slate-500 focus:outline-none focus:border-emerald-500 font-mono leading-relaxed transition-colors resize-y min-h-[16rem]"
              required
            />
          </div>
        ) : (
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,image/png,image/jpeg,image/webp,.txt"
              onChange={handleFileSelect}
              className="hidden"
            />
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleFileDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-2xl p-8 text-center cursor-pointer transition-all ${
                dragOver
                  ? 'border-emerald-500 bg-emerald-50'
                  : 'border-slate-300 bg-slate-50/40 hover:border-slate-400 hover:bg-slate-50/60'
              }`}
            >
              <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-slate-100 flex items-center justify-center text-slate-600">
                {selectedFile ? (
                  <FileText className="w-6 h-6 text-emerald-600" />
                ) : (
                  <Upload className="w-6 h-6" />
                )}
              </div>
              {selectedFile ? (
                <div>
                  <p className="text-sm font-semibold text-emerald-600">{selectedFile.name}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {(selectedFile.size / 1024).toFixed(1)} KB — Click to change file
                  </p>
                </div>
              ) : (
                <div>
                  <p className="text-sm font-semibold text-slate-700">
                    Drop your offer letter PDF or screenshot here
                  </p>
                  <p className="text-xs text-slate-500 mt-1">
                    Supports PDF, PNG, JPG, or screenshot images up to 10MB
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Informational callout */}
        <div className="p-3.5 rounded-xl bg-slate-50/90 border border-slate-200 text-xs text-slate-500 flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
          <p>
            AsliOffer extracts entities and queries public search data in real-time via SerpApi.
            We will never store private Aadhaar, PAN, or financial numbers.
          </p>
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={isLoading || (activeTab === 'text' && !content.trim()) || (activeTab === 'file' && !selectedFile)}
          className="w-full py-3.5 px-6 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold text-sm tracking-wide shadow-lg shadow-emerald-200 transition-all flex items-center justify-center gap-2"
        >
          {isLoading ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              <span>Running Live Public Footprint Investigation...</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              <span>Investigate Offer with AI Agents</span>
            </>
          )}
        </button>
      </form>
    </div>
  );
};
