import React, { useState, useRef } from 'react';
import { Upload, FileText, Sparkles, AlertCircle, Check, X, HelpCircle } from 'lucide-react';

const MAX_FILE_BYTES = 5 * 1024 * 1024;
const MAX_TEXT_CHARS = 20000;

interface FileUploadProps {
  onAnalyze: (payload: { title: string; content: string; file?: File; sample?: boolean }) => void;
  isLoading: boolean;
}

export const FileUpload: React.FC<FileUploadProps> = ({ onAnalyze, isLoading }) => {
  const [activeTab, setActiveTab] = useState<'text' | 'file'>('text');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  // True only while the text is an unmodified built-in preset; sent as sample=true.
  const [isSample, setIsSample] = useState(false);
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

  // A real internship mail received by a candidate in Sept 2026. No fee is asked
  // for yet, which is exactly why it matters: the company has no public footprint
  // and the sender gives no verifiable address.
  const sampleUnverifiableText = `Subject: Coorix Internship Selection Process Round 1 Notification
From: Coorix HR

Dear Applicant,

Thank you for showing interest in the Coorix Internship Drive.

We're excited to inform you that the selection process for this batch begins today. Please read the details below carefully.

Open Positions:
1) Data Analyst Intern
2) Business Analyst Intern
3) Web Developer Intern
4) AI/ML Intern
5) Data Science Intern
Stipend: stipend of upto Rs 15,000.

Selection Process - 3 Rounds:

1. Screening Round (Today) - A short live session covering the program structure, eligibility, and domain selection. Attendance here is mandatory to move forward.

The details of the screening round are as follows:
Date: 28/09/2026
Time: 11:00 AM
Mode: Online (Google Meet)
Duration: Approximately 20-30 minutes.
The screening round will be conducted online via Google Meet. The meeting link will be shared with you at least 1 hour before the start of the session.

2. Domain Exam (Within 24 hours of screening) - A skill-based test in your chosen domain. Cutoff: 70%. One attempt only, so please ensure a stable environment before you begin.
3. Technical Interview (By invitation only) - For candidates who clear the domain exam. This round focuses on your existing project work and how you approach real problems.

What to Do Next:
- Choose your domain in advance - this choice is locked once the shortlist is finalized.
- Keep your calendar clear for the following 24-48 hours, as the exam and interview invites move quickly.

Who This Is For:
This program is built for candidates who already have working knowledge in their domain and can defend at least one project they've built. It is not a beginner training program - live client work starts from week one.

We look forward to seeing you in the screening round.

Best regards,
Shraddha Rajput
HR Manager`;

  const handlePresetScam = () => {
    setTitle('TCS Associate Software Engineer Offer Letter');
    setContent(sampleScamText);
    setSelectedFile(null);
    setIsSample(true);
    setActiveTab('text');
  };

  const handlePresetLegit = () => {
    setTitle('Infosys Systems Engineer Specialist Offer');
    setContent(sampleLegitText);
    setSelectedFile(null);
    setIsSample(true);
    setActiveTab('text');
  };

  const handlePresetUnverifiable = () => {
    setTitle('Coorix Internship Selection Process Round 1');
    setContent(sampleUnverifiableText);
    setSelectedFile(null);
    setIsSample(true);
    setActiveTab('text');
  };

  const [fileError, setFileError] = useState<string | null>(null);

  // Mirrors the backend limits so the user hears about a bad file before uploading it.
  const acceptFile = (file: File): boolean => {
    if (!/\.(pdf|png|jpe?g|webp)$/i.test(file.name)) {
      setFileError('Unsupported file type. Upload a PDF, PNG, JPG or WEBP file, or paste the text.');
      return false;
    }
    if (file.size > MAX_FILE_BYTES) {
      setFileError('This file is larger than 5 MB. Upload a smaller file or paste the text.');
      return false;
    }
    setFileError(null);
    return true;
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (!acceptFile(file)) return;
      setSelectedFile(file);
      if (!title) setTitle(file.name.replace(/\.[^/.]+$/, ''));
      setActiveTab('file');
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (!acceptFile(file)) return;
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
      if (content.length > MAX_TEXT_CHARS) return;
      onAnalyze({
        title: title || 'Pasted Job Offer Message',
        content,
        sample: isSample,
      });
    }
  };

  return (
    <div className="glass-panel rounded-xl p-6 sm:p-8">
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
            <X className="w-3.5 h-3.5" />
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
          <button
            type="button"
            onClick={handlePresetUnverifiable}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-50 hover:bg-amber-100 text-amber-700 border border-amber-200 transition-colors flex items-center gap-1.5"
          >
            <HelpCircle className="w-3.5 h-3.5" />
            <span>Load Unverifiable Employer (Coorix)</span>
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
              onChange={(e) => {
                setContent(e.target.value);
                setIsSample(false);
              }}
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
              accept=".pdf,.png,.jpg,.jpeg,.webp"
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
              className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
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
                    PDF, PNG, JPG or WEBP, up to 5 MB
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {fileError && (
          <p role="alert" className="text-xs text-rose-700">{fileError}</p>
        )}
        {activeTab === 'text' && content.length > MAX_TEXT_CHARS && (
          <p role="alert" className="text-xs text-rose-700">
            The text is longer than {MAX_TEXT_CHARS.toLocaleString()} characters. Paste only the offer itself.
          </p>
        )}

        {/* Informational callout */}
        <div className="p-3.5 rounded-xl bg-slate-50/90 border border-slate-200 text-xs text-slate-500 flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
          <p>
            ID numbers, bank details and one-time codes are removed before any search. The offer text is
            kept for 7 days so you can reopen the report, then deleted.
          </p>
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={isLoading || (activeTab === 'text' && (!content.trim() || content.length > MAX_TEXT_CHARS)) || (activeTab === 'file' && !selectedFile)}
          className="w-full py-3.5 px-6 rounded-xl bg-slate-900 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold text-sm tracking-wide transition-all flex items-center justify-center gap-2"
        >
          {isLoading ? (
            <>
              <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              <span>Uploading and reading the offer…</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4" />
              <span>Continue: check the details</span>
            </>
          )}
        </button>
      </form>
    </div>
  );
};
