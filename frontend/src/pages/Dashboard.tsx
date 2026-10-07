import React from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  Building,
  UserCheck,
  IndianRupee,
  AlertTriangle,
  FileText,
  ListChecks,
  ShieldCheck,
} from 'lucide-react';
import { OutcomeBadge } from '../components/OutcomeBadge';
import type { ComponentProps } from 'react';

type Outcome = ComponentProps<typeof OutcomeBadge>['outcome'];

const agents = [
  {
    icon: Building,
    title: 'Company',
    body: 'Finds the employer’s official domain and careers pages from public search results.',
  },
  {
    icon: UserCheck,
    title: 'Recruiter',
    body: 'Checks the sender’s email belongs to the employer — not Gmail or a lookalike domain.',
  },
  {
    icon: IndianRupee,
    title: 'Salary',
    body: 'Compares the stated pay with public figures for the role to catch bait offers.',
  },
  {
    icon: AlertTriangle,
    title: 'Scam signals',
    body: 'Flags fee, deposit, UPI and OTP demands — without flagging “we never charge fees”.',
  },
];

const steps = [
  { icon: FileText, title: 'Add your offer', body: 'Upload the letter or paste the email or WhatsApp message.' },
  { icon: ListChecks, title: 'Confirm the details', body: 'Check what we read before anything is searched.' },
  { icon: ShieldCheck, title: 'Get the verdict', body: 'See the result with every source linked as proof.' },
];

const samples: { to: string; outcome: Outcome; title: string; body: string; tags: string[] }[] = [
  {
    to: '/samples/impersonation',
    outcome: 'HIGH_RISK',
    title: 'Nimbus Infotech — Graduate Engineer Trainee',
    body: 'Sent from Gmail while the employer has its own domain, and asks for a ₹15,000 laptop deposit via UPI.',
    tags: ['UPI fee demanded', 'Personal webmail'],
  },
  {
    to: '/samples/sparse-startup',
    outcome: 'CANNOT_VERIFY',
    title: 'Coorix Labs — Backend Developer Intern',
    body: 'A small startup with almost no public footprint. No fee is asked, so the report says it cannot verify — not that it is a scam.',
    tags: ['Sparse footprint', 'No fee demand'],
  },
];

export const Dashboard: React.FC = () => {
  return (
    <div className="space-y-24 pb-16">
      {/* Hero */}
      <section className="relative pt-16 sm:pt-24 text-center">
        <div className="hero-grid absolute inset-x-0 -top-6 h-96 -z-10" aria-hidden />

        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-white border border-slate-200 text-slate-600 text-xs font-medium shadow-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          Built for Indian freshers · Powered by SerpApi
        </div>

        <h1 className="mt-6 text-4xl sm:text-6xl font-bold tracking-tight text-slate-900 max-w-3xl mx-auto leading-[1.08]">
          Is your job offer real?
          <br />
          <span className="text-emerald-600">Check it with proof.</span>
        </h1>

        <p className="mt-5 text-base sm:text-lg text-slate-500 max-w-xl mx-auto leading-relaxed">
          Scammers can copy a logo, but not a company’s whole public footprint. AsliOffer checks your offer against
          live public records and shows you the evidence.
        </p>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            to="/upload"
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-5 py-3 rounded-lg bg-slate-900 hover:bg-slate-800 text-white font-medium text-sm transition-colors shadow-sm"
          >
            Verify an offer
            <ArrowRight className="w-4 h-4" />
          </Link>
          <Link
            to="/samples/impersonation"
            className="w-full sm:w-auto inline-flex items-center justify-center px-5 py-3 rounded-lg bg-white hover:bg-slate-50 border border-slate-200 text-slate-700 font-medium text-sm transition-colors"
          >
            See a sample report
          </Link>
        </div>

        <p className="mt-4 text-xs text-slate-400">No sign-up · Your case is deleted after 7 days</p>
      </section>

      {/* How it works */}
      <section className="max-w-5xl mx-auto">
        <SectionHeading eyebrow="How it works" title="Three simple steps" />
        <ol className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {steps.map((s, i) => (
            <li key={s.title} className="glass-card rounded-xl p-5">
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-700 flex items-center justify-center">
                  <s.icon className="w-4 h-4" />
                </span>
                <span className="text-xs font-medium text-slate-400">Step {i + 1}</span>
              </div>
              <h3 className="mt-4 text-sm font-semibold text-slate-900">{s.title}</h3>
              <p className="mt-1 text-sm text-slate-500 leading-relaxed">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Agents */}
      <section className="max-w-5xl mx-auto">
        <SectionHeading
          eyebrow="What we check"
          title="Four independent checks"
          sub="Each agent looks at one part of the offer and cites the public sources it used."
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {agents.map((a) => (
            <div key={a.title} className="glass-card rounded-xl p-5 hover:border-slate-300">
              <a.icon className="w-5 h-5 text-slate-700" />
              <h3 className="mt-4 text-sm font-semibold text-slate-900">{a.title}</h3>
              <p className="mt-1 text-sm text-slate-500 leading-relaxed">{a.body}</p>
            </div>
          ))}
        </div>
        <p className="mt-6 text-center text-sm text-slate-500">
          When the trail is too thin to check, AsliOffer says so instead of guessing.
        </p>
      </section>

      {/* Samples */}
      <section className="max-w-5xl mx-auto">
        <SectionHeading
          eyebrow="Examples"
          title="Sample reports"
          sub="Built from synthetic data to show the report — not live investigations."
        />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {samples.map((s) => (
            <Link
              key={s.to}
              to={s.to}
              className="glass-card group rounded-xl p-6 flex flex-col hover:border-slate-300 hover:-translate-y-0.5"
            >
              <span className="self-start"><OutcomeBadge outcome={s.outcome} /></span>
              <h3 className="mt-4 text-base font-semibold text-slate-900">{s.title}</h3>
              <p className="mt-1.5 text-sm text-slate-500 leading-relaxed">{s.body}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                {s.tags.map((t) => (
                  <span key={t} className="text-xs px-2 py-0.5 rounded-md bg-slate-100 text-slate-600">
                    {t}
                  </span>
                ))}
              </div>
              <span className="mt-6 pt-4 border-t border-slate-100 text-sm font-medium text-slate-900 inline-flex items-center gap-1">
                View report
                <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section className="max-w-5xl mx-auto">
        <div className="rounded-2xl bg-slate-900 px-6 py-12 sm:px-12 text-center">
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">Got an offer that feels off?</h2>
          <p className="mt-2 text-slate-400 text-sm">Check it before you pay anything or share any OTP.</p>
          <Link
            to="/upload"
            className="mt-6 inline-flex items-center gap-2 px-5 py-3 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-sm transition-colors"
          >
            Verify an offer
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </section>
    </div>
  );
};

const SectionHeading: React.FC<{ eyebrow: string; title: string; sub?: string }> = ({ eyebrow, title, sub }) => (
  <div className="text-center mb-8">
    <p className="text-xs font-semibold uppercase tracking-wider text-emerald-600">{eyebrow}</p>
    <h2 className="mt-2 text-2xl sm:text-3xl font-bold tracking-tight text-slate-900">{title}</h2>
    {sub && <p className="mt-2 text-sm text-slate-500 max-w-lg mx-auto">{sub}</p>}
  </div>
);
