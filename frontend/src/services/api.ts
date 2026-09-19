import { Offer, OfferUploadResponse, VerificationReport } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const mockSampleReportHighRisk: VerificationReport = {
  offer_id: 101,
  title: "TCS Associate Software Engineer Offer Letter",
  risk_level: "HIGH_RISK",
  risk_score: 0.94,
  summary: "HIGH RISK DETECTED: This offer shows severe hallmarks of an employment scam impersonating Tata Consultancy Services. Immediate caution is advised. Critical indicators include unauthorized email communication from a free webmail account and an illegal upfront laptop security deposit demand.",
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
          description: "Verified domain with official SSL certificates and BSE/NSE public stock listings.",
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
      details: { mca_cin: "L22210MH1995PLC084781", status: "Active" }
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
      summary: "Confirmed advance fee fraud: Request for ₹15,000 refundable security deposit via UPI violates Ministry of Labour regulations.",
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
    "Tata Consultancy Services is a legitimate registered company in India."
  ],
  official_company_info: {
    name: "Tata Consultancy Services (TCS)",
    website: "https://www.tcs.com",
    careers_url: "https://www.tcs.com/careers",
    mca_status: "Active Public Limited (MCA India)",
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

export const mockSampleReportVerified: VerificationReport = {
  offer_id: 102,
  title: "Infosys Systems Engineer Specialist Offer",
  risk_level: "VERIFIED",
  risk_score: 0.12,
  summary: "VERIFIED EVIDENCE FOOTPRINT: The extracted credentials, company presence, official corporate sender domain, and compensation parameters align with verified employment practices for Infosys Limited.",
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
      summary: "Official corporate footprint, registered MCA entity, and public job portal confirmed.",
      evidence: [
        {
          source_url: "https://www.infosys.com",
          title: "Infosys Corporate Portal",
          description: "Global IT leader registered with MCA and listed on BSE, NSE, and NYSE.",
          evidence_type: "COMPANY",
          confidence: 0.99,
        }
      ],
      details: { mca_cin: "L85110KA1981PLC013115", status: "Active" }
    },
    {
      agent_name: "RecruiterAgent",
      verdict: "VERIFIED",
      confidence: 0.94,
      summary: "Recruiter email domain strictly matches the verified corporate domain (@infosys.com).",
      evidence: [
        {
          source_url: "https://www.infosys.com",
          title: "Infosys Mail Exchange Verification",
          description: "DKIM/SPF and MX records confirmed for sender domain infosys.com.",
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
    "Official corporate phone number and registered campus address verified.",
    "Salary conforms to verified fresher benchmarks."
  ],
  official_company_info: {
    name: "Infosys Limited",
    website: "https://www.infosys.com",
    careers_url: "https://career.infosys.com",
    mca_status: "Active Public Limited",
    recruitment_policy: "Infosys does not charge fees at any point in the recruitment process."
  },
  recommended_actions: [
    "Verify your candidate reference ID directly on the Infosys Career Portal.",
    "Review service agreements and non-disclosure clauses prior to formal signing.",
    "Confirm reporting date and documents with campus recruitment coordinators."
  ],
  generated_at: new Date().toISOString(),
};

export const api = {
  async checkHealth() {
    try {
      const res = await fetch(`${API_BASE_URL}/health`);
      return await res.json();
    } catch {
      return { status: "offline", service: "AsliOffer Mock Mode" };
    }
  },

  async uploadOffer(formData: FormData): Promise<OfferUploadResponse> {
    try {
      const res = await fetch(`${API_BASE_URL}/offers/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error("Upload failed");
      return await res.json();
    } catch {
      // Fallback mock response for standalone frontend testing
      return {
        offer_id: 101,
        title: (formData.get('title') as string) || "Uploaded Offer Letter",
        status: "PENDING",
        message: "Offer received (mock fallback). Ready for forensic multi-agent audit.",
      };
    }
  },

  async uploadOfferText(title: string, raw_content: string): Promise<OfferUploadResponse> {
    const formData = new FormData();
    formData.append('title', title);
    formData.append('source_type', 'text');
    formData.append('raw_content', raw_content);
    return this.uploadOffer(formData);
  },

  async getOffer(id: number): Promise<Offer> {
    try {
      const res = await fetch(`${API_BASE_URL}/offers/${id}`);
      if (!res.ok) throw new Error("Failed to fetch offer");
      return await res.json();
    } catch {
      return {
        id,
        title: "TCS Associate Software Engineer Offer Letter",
        source_type: "pdf",
        raw_content: "Mock raw content",
        risk_score: 0.94,
        status: "COMPLETED",
        risk_level: "HIGH_RISK",
        created_at: new Date().toISOString(),
      };
    }
  },

  async getOfferReport(id: number): Promise<VerificationReport> {
    try {
      const res = await fetch(`${API_BASE_URL}/offers/${id}/report`);
      if (!res.ok) throw new Error("Failed to load report");
      return await res.json();
    } catch {
      // Return high-risk demo mock for offer 101, verified demo for 102
      return id === 102 ? mockSampleReportVerified : mockSampleReportHighRisk;
    }
  },

  async runAnalysis(offer_id: number): Promise<VerificationReport> {
    try {
      const res = await fetch(`${API_BASE_URL}/analysis/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ offer_id }),
      });
      if (!res.ok) throw new Error("Analysis failed");
      return await res.json();
    } catch {
      return this.getOfferReport(offer_id);
    }
  },
};
