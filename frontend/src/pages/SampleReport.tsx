import React from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { OfferReport } from './OfferReport';
import { SAMPLE_REPORTS } from '../samples/sampleReports';

/** Explicit, clearly bannered sample report. The only place sample data is shown. */
export const SampleReport: React.FC = () => {
  const { key } = useParams<{ key: string }>();
  const entry = key ? SAMPLE_REPORTS[key] : undefined;
  if (!entry) return <Navigate to="/" replace />;
  return <OfferReport key={entry.key} sample={{ label: entry.label, report: entry.report }} />;
};
