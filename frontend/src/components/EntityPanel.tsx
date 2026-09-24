import React from 'react';
import { Building2, Mail, Phone, Briefcase, IndianRupee, AlertOctagon, Flag } from 'lucide-react';
import { ExtractedEntities } from '../types';

interface EntityPanelProps {
  entities: ExtractedEntities;
}

export const EntityPanel: React.FC<EntityPanelProps> = ({ entities }) => {
  return (
    <div className="glass-panel rounded-2xl p-6">
      <div className="flex items-center justify-between mb-5">
        <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
          <Building2 className="w-5 h-5 text-emerald-600" />
          <span>Extracted Entities & Claims</span>
        </h3>
        <span className="text-xs text-slate-500 bg-slate-100/80 px-2.5 py-1 rounded-md border border-slate-300">
          Automated Extraction Layer
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Company */}
        <div className="p-3.5 rounded-xl bg-slate-50/60 border border-slate-200">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-1">
            <Building2 className="w-3.5 h-3.5 text-blue-600" />
            <span>Target Company</span>
          </div>
          <p className="text-sm font-semibold text-slate-900 truncate">
            {entities.company_name || 'Not detected'}
          </p>
        </div>

        {/* Role */}
        <div className="p-3.5 rounded-xl bg-slate-50/60 border border-slate-200">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-1">
            <Briefcase className="w-3.5 h-3.5 text-indigo-600" />
            <span>Role / Designation</span>
          </div>
          <p className="text-sm font-semibold text-slate-900 truncate">
            {entities.role_title || 'Not specified'}
          </p>
        </div>

        {/* Salary */}
        <div className="p-3.5 rounded-xl bg-slate-50/60 border border-slate-200">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-1">
            <IndianRupee className="w-3.5 h-3.5 text-emerald-600" />
            <span>Offered Compensation</span>
          </div>
          <p className="text-sm font-semibold text-slate-900 truncate">
            {entities.offered_salary || 'Not specified'}
          </p>
        </div>

        {/* Recruiter Email */}
        <div className="p-3.5 rounded-xl bg-slate-50/60 border border-slate-200">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-1">
            <Mail className="w-3.5 h-3.5 text-purple-600" />
            <span>Recruiter Email</span>
          </div>
          <p className="text-sm font-semibold text-slate-900 truncate">
            {entities.recruiter_email || 'Not provided'}
          </p>
          {entities.recruiter_email && (entities.recruiter_email.includes('gmail.com') || entities.recruiter_email.includes('outlook.com')) && (
            <span className="inline-block mt-1 text-[10px] text-rose-600 font-medium">
              ⚠ Free Webmail Domain
            </span>
          )}
        </div>

        {/* Recruiter Phone / Contact */}
        <div className="p-3.5 rounded-xl bg-slate-50/60 border border-slate-200">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-1">
            <Phone className="w-3.5 h-3.5 text-cyan-600" />
            <span>Phone / Handle</span>
          </div>
          <p className="text-sm font-semibold text-slate-900 truncate">
            {entities.recruiter_phone || 'Not provided'}
          </p>
          {entities.recruiter_name && (
            <p className="text-xs text-slate-500 mt-0.5">Name: {entities.recruiter_name}</p>
          )}
        </div>

        {/* Demanded Fee (Critical Flag) */}
        <div
          className={`p-3.5 rounded-xl border ${
            entities.demanded_fee
              ? 'bg-rose-50 border-rose-300 text-rose-800'
              : 'bg-slate-50/60 border-slate-200'
          }`}
        >
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500 mb-1">
            <AlertOctagon
              className={`w-3.5 h-3.5 ${
                entities.demanded_fee ? 'text-rose-600' : 'text-slate-500'
              }`}
            />
            <span className={entities.demanded_fee ? 'text-rose-600 font-bold' : ''}>
              Upfront Fee / Deposit
            </span>
          </div>
          <p
            className={`text-sm font-semibold truncate ${
              entities.demanded_fee ? 'text-rose-700' : 'text-slate-500'
            }`}
          >
            {entities.demanded_fee || 'None requested (Safe)'}
          </p>
          {entities.payment_method && (
            <p className="text-xs text-rose-600 mt-0.5">
              Demanded via: {entities.payment_method}
            </p>
          )}
        </div>
      </div>

      {/* Extracted Flags */}
      {entities.flags && entities.flags.length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-200/80 flex items-center gap-2 flex-wrap">
          <span className="text-xs text-slate-500 flex items-center gap-1">
            <Flag className="w-3.5 h-3.5 text-amber-600" />
            <span>Active Trigger Flags:</span>
          </span>
          {entities.flags.map((flag, idx) => (
            <span
              key={idx}
              className="text-[11px] px-2.5 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 font-mono"
            >
              {flag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
