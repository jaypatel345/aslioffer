import { VerificationReport } from '../types';

/**
 * Illustrative sample reports for the Dashboard.
 *
 * These are hand-written examples, not the output of a live investigation, and
 * are only reachable through the explicit /samples/:key route, which shows a
 * banner saying so. They are never substituted for a real case: API failures
 * surface as errors (see services/api.ts).
 */

const impersonationSample: VerificationReport = {
  offer_id: 0,
  title: "TCS Associate Software Engineer Offer Letter",
  risk_level: "HIGH_RISK",
  risk_score: 0.94,
  summary: "HIGH RISK DETECTED: This offer shows severe hallmarks of an employment scam impersonating Tata Consultancy Services. Immediate caution is advised. Critical indicators include unauthorized email communication from a free webmail account and an upfront laptop security deposit demand.",
  extracted_entities: {
    company_name: "Tata Consultancy Services (TCS)",
    recruiter_name: "Rohit Sharma",
    recruiter_email: "rohit.tcs.hiring@gmail.com",
    recruiter_phone: "+91 9876543210",
    role_title: "Associate Software Engineer",
    offered_salary: "₹8.5 LPA",
    location: "Remote / Hybrid (Bengaluru)",
    demanded_fee: "₹15,000 Laptop Security Deposit",
    payment_method: "UPI (tcs-recruiter@upi)",
    flags: ["DEMANDS_UPFRONT_FEE", "PUBLIC_EMAIL_DOMAIN_USED", "TELEGRAM_CONTACT_SUSPICIOUS"],
  },
  findings: [
    {
      agent_name: "CompanyAgent",
      verdict: "VERIFIED",
      confidence: 0.96,
      summary: "Legitimate corporate footprint and official careers presence confirmed for Tata Consultancy Services.",
      evidence: [
        {
          source_url: "https://www.tcs.com",
          title: "TCS Official Corporate Domain",
          description: "Search results consistently point to tcs.com as the employer's official domain.",
          evidence_type: "COMPANY",
          confidence: 0.98,
        },
        {
          source_url: "https://www.tcs.com/careers",
          title: "TCS Official Careers Portal & Warning Notice",
          description: "TCS explicitly states: 'TCS never charges any fee at any stage of recruitment or for laptop/equipment security.'",
          evidence_type: "COMPANY",
          confidence: 0.99,
        }
      ],
      details: {}
    },
    {
      agent_name: "RecruiterAgent",
      verdict: "HIGH_RISK",
      confidence: 0.97,
      summary: "Critical mismatch: Recruiter sent communications from personal Gmail account 'rohit.tcs.hiring@gmail.com' rather than official @tcs.com domain.",
      evidence: [
        {
          source_url: "https://cybercrime.gov.in",
          title: "Spoofed Enterprise Recruiter Pattern",
          description: "All genuine TCS hiring correspondence originates strictly from @tcs.com domains. Free webmail providers are prohibited by enterprise HR policy.",
          evidence_type: "RECRUITER",
          confidence: 0.98,
        }
      ],
      details: { domain_match: false, is_free_email: true }
    },
    {
      agent_name: "SalaryAgent",
      verdict: "VERIFIED",
      confidence: 0.85,
      summary: "Stated compensation of ₹8.5 LPA is within the upper percentile for Ninja/Digital entry-level packages.",
      evidence: [
        {
          source_url: "https://www.ambitionbox.com/salaries/tcs-salaries",
          title: "TCS Software Engineer Salary Range (AmbitionBox)",
          description: "Average entry-level compensation ranges between ₹3.6 LPA (Ninja) and ₹9.0 LPA (Prime/Innovator).",
          evidence_type: "SALARY",
          confidence: 0.88,
        }
      ],
      details: { benchmark_range: "₹3.6 - ₹9.0 LPA", anomaly: false }
    },
    {
      agent_name: "ScamAgent",
      verdict: "HIGH_RISK",
      confidence: 0.99,
      summary: "The letter demands a ₹15,000 'refundable security deposit' via UPI before joining — an upfront payment demand.",
      evidence: [
        {
          source_url: "https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
          title: "Ministry of Home Affairs Advisory - Job Scams",
          description: "Scammers falsely claim deposits are required for couriered company laptops or training kits.",
          evidence_type: "SCAM_REPORT",
          confidence: 0.99,
        },
        {
          source_url: "https://x.com/cyberdost",
          title: "CyberDost Official Advisory",
          description: "Never transfer money to any individual or UPI QR code for an employment offer or interview scheduling.",
          evidence_type: "SCAM_REPORT",
          confidence: 0.95,
        }
      ],
      details: { demanded_fee: "₹15,000", payment_method: "UPI", scam_flagged: true }
    }
  ],
  red_flags: [
    "Recruiter contacted using a free @gmail.com address instead of official @tcs.com.",
    "Demanded an upfront fee of ₹15,000 as a 'laptop security deposit' via personal UPI.",
    "Pressure to transfer funds within 24 hours to secure onboarding date."
  ],
  green_flags: [
    "Search results consistently point to tcs.com as the employer's official domain."
  ],
  official_company_info: {
    name: "Tata Consultancy Services (TCS)",
    website: "https://www.tcs.com",
    careers_url: "https://www.tcs.com/careers",
        recruitment_policy: "TCS does not ask candidates for any recruitment fees, screening deposits, or equipment charges."
  },
  recommended_actions: [
    "DO NOT transfer ₹15,000 or any amount via UPI or bank transfer.",
    "DO NOT share Aadhaar, PAN card, or bank account statements.",
    "Report this phone number and UPI handle immediately to the National Cyber Crime Reporting Portal (cybercrime.gov.in) or call 1930.",
    "Cross-check your application status directly at the official TCS NextStep portal (nextstep.tcs.com)."
  ],
  generated_at: new Date().toISOString(),
};

const corporateDomainSample: VerificationReport = {
  offer_id: 0,
  title: "Infosys Systems Engineer Specialist Offer",
  risk_level: "VERIFIED",
  risk_score: 0.12,
  summary: "No strong risk signals: the sender domain matches the employer's official domain and no fee is requested. Only Infosys can confirm the offer itself.",
  extracted_entities: {
    company_name: "Infosys Limited",
    recruiter_name: "Pooja Kulkarni",
    recruiter_email: "pooja.kulkarni@infosys.com",
    recruiter_phone: "+91 80 2852 0261",
    role_title: "Systems Engineer Specialist",
    offered_salary: "₹6.25 LPA",
    location: "Bengaluru / Electronics City",
    demanded_fee: undefined,
    payment_method: undefined,
    flags: [],
  },
  findings: [
    {
      agent_name: "CompanyAgent",
      verdict: "VERIFIED",
      confidence: 0.98,
      summary: "Official domain and public careers portal found in search results.",
      evidence: [
        {
          source_url: "https://www.infosys.com",
          title: "Infosys Corporate Portal",
          description: "Search results consistently point to infosys.com as the employer's official domain.",
          evidence_type: "COMPANY",
          confidence: 0.99,
        }
      ],
      details: {}
    },
    {
      agent_name: "RecruiterAgent",
      verdict: "VERIFIED",
      confidence: 0.94,
      summary: "Recruiter email domain strictly matches the verified corporate domain (@infosys.com).",
      evidence: [
        {
          source_url: "https://www.infosys.com",
          title: "Sender domain matches official domain",
          description: "The sender address uses infosys.com, the resolved official domain. This checks the domain only, not who sent the letter.",
          evidence_type: "RECRUITER",
          confidence: 0.95,
        }
      ],
      details: { domain_match: true, is_free_email: false }
    },
    {
      agent_name: "SalaryAgent",
      verdict: "VERIFIED",
      confidence: 0.90,
      summary: "Offered CTC of ₹6.25 LPA matches official Specialist Programmer / SES fresher bands.",
      evidence: [
        {
          source_url: "https://www.ambitionbox.com/salaries/infosys-salaries",
          title: "AmbitionBox Infosys Salary Band",
          description: "Standard SES role compensation in India is between ₹5.0 LPA and ₹7.0 LPA.",
          evidence_type: "SALARY",
          confidence: 0.92,
        }
      ],
      details: { benchmark_range: "₹5.0 - ₹7.0 LPA", anomaly: false }
    },
    {
      agent_name: "ScamAgent",
      verdict: "VERIFIED",
      confidence: 0.95,
      summary: "No fee demands, security deposits, or suspicious communication channels detected.",
      evidence: [
        {
          source_url: "https://cybercrime.gov.in",
          title: "Clean Footprint Audit",
          description: "No advance payment demands or red flags recorded for this offer communication.",
          evidence_type: "SCAM_REPORT",
          confidence: 0.95,
        }
      ],
      details: { demanded_fee: null, scam_flagged: false }
    }
  ],
  red_flags: [],
  green_flags: [
    "Email sent from legitimate corporate domain (@infosys.com).",
    "No registration or training fee demanded.",
        "Salary conforms to verified fresher benchmarks."
  ],
  official_company_info: {
    name: "Infosys Limited",
    website: "https://www.infosys.com",
    careers_url: "https://career.infosys.com",
        recruitment_policy: "Infosys does not charge fees at any point in the recruitment process."
  },
  recommended_actions: [
    "Verify your candidate reference ID directly on the Infosys Career Portal.",
    "Review service agreements and non-disclosure clauses prior to formal signing.",
    "Confirm reporting date and documents with campus recruitment coordinators."
  ],
  generated_at: new Date().toISOString(),
};

export interface SampleEntry {
  key: string;
  label: string;
  report: VerificationReport;
}

export const SAMPLE_REPORTS: Record<string, SampleEntry> = {
  impersonation: {
    key: 'impersonation',
    label: 'Impersonation with upfront fee',
    report: impersonationSample,
  },
  'corporate-domain': {
    key: 'corporate-domain',
    label: 'Corporate sender domain, no fee requested',
    report: corporateDomainSample,
  },
};
