import io
import re
from typing import Optional, Dict, Any, List
from app.schemas.analysis import ExtractedEntities, ExtractedData
from app.services.ai.gemini_client import GeminiClient
from app.services.ai.groq_client import GroqClient
from app.services.extractor.claim_models import (
    Claim,
    ClaimKind,
    ExtractionResult,
    ExtractionStatus,
    ConfidenceTier,
    SourceSpan,
    UnresolvedAmbiguity,
    ExtractionWarning,
)
from app.services.extractor.grounded_parser import GroundedEntityParser
from app.services.agents.scam_classifier import sanitize_and_redact_secrets
from app.core.logging import logger


class EntityExtractor:
    """
    Extracts key entities from offer letters, screenshots, recruiter messages, or emails.
    Supports both claim-based extraction (contract v1.0.1) and legacy ExtractedData adapters.
    Document reading uses local PDF text extraction; unavailable local reading returns a clear refusal.
    """

    def __init__(
        self,
        gemini_client: Optional[GeminiClient] = None,
        groq_client: Optional[GroqClient] = None,
    ):
        self.gemini_client = gemini_client or GeminiClient()
        self.groq_client = groq_client or GroqClient()
        self.parser = GroundedEntityParser()

    def extract_claims(self, text: str, source_type: str = "text") -> ExtractionResult:
        """
        Extracts validated, contract v1.0.1 compliant claims with grounded provenance,
        semantic role attribution, and explicit ambiguity records.
        """
        return self.parser.parse(text, source_type=source_type)

    async def extract_entities(self, text: str) -> ExtractedData:
        """
        Extracts structured ExtractedData from text using Gemini with automatic regex fallback.
        Handles timeout, invalid JSON, rate limit, and API errors transparently.
        Sanitizes text before passing to external models and validates output grounding.
        """
        return (await self.extract_claims_async(text)).to_extracted_data()

    async def extract_claims_async(self, text: str, source_type: str = "text") -> ExtractionResult:
        """Model proposals never bypass deterministic role/provenance validation."""
        result = self.extract_claims(text, source_type)
        if self.gemini_client and self.gemini_client.api_key:
            try:
                proposal = await self.gemini_client.extract_entities(result.sanitized_source_buffer)
                canonical = result.to_extracted_data()
                fields = ("company", "recruiter_email", "recruiter_phone", "job_role", "salary",
                          "website", "joining_date", "address", "payment_amount", "payment_method")
                if any(getattr(proposal, field, None) not in (None, getattr(canonical, field)) for field in fields):
                    result.warnings.append(ExtractionWarning(
                        code="MODEL_PROPOSAL_REJECTED",
                        message="Model proposals did not match grounded, role-attributed document claims."))
            except Exception:
                result.warnings.append(ExtractionWarning(
                    code="MODEL_EXTRACTION_UNAVAILABLE",
                    message="Model extraction unavailable; deterministic grounded extraction retained."))
        return result

    def _backfill_salary_fields(self, data: ExtractedData) -> ExtractedData:
        """
        Make the local parser authoritative for salary_amount / salary_period.
        """
        if data.salary:
            _, amount, period = self._detect_salary(data.salary)
            if amount is not None:
                data.salary_amount = amount
            if period:
                data.salary_period = period
        return data

    @staticmethod
    def _extract_pdf_text_local(file_bytes: bytes) -> str:
        """
        Privacy-preserving local extraction of PDF text using pypdf without external network calls.
        """
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages = []
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    pages.append(t.strip())
            return "\n\n".join(pages).strip()
        except Exception as e:
            logger.warning("Local PDF extraction failed: %s", type(e).__name__)
            return ""

    async def extract_from_document(self, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        """
        Extracts text (OCR) and structured entities from PDF or image documents.
        Reads PDFs locally and refuses automatic external processing of unreadable binaries.
        Returns:
            {
                "ocr_text": str,
                "entities": ExtractedData
            }
        """
        failures: List[str] = []

        # Privacy & safety: Refuse external vision calls on unsupported/binary formats
        norm_mime = (mime_type or "").lower().split(";")[0].strip()
        supported_mimes = {"application/pdf", "image/png", "image/jpeg", "image/jpg", "image/webp"}
        if norm_mime not in supported_mimes:
            logger.warning("Unsupported document format '%s'; refusing external vision call.", norm_mime)
            return {
                "ocr_text": "",
                "entities": self.extract_regex(""),
                "error": f"Unsupported document format '{norm_mime}'. Please upload a PDF or image, or paste text.",
            }

        # Local PDF extraction first (privacy-preserving, no external network call)
        if norm_mime == "application/pdf":
            local_pdf_text = self._extract_pdf_text_local(file_bytes)
            if local_pdf_text and local_pdf_text.strip():
                sanitized_ocr = self.extract_claims(local_pdf_text, "pdf").sanitized_source_buffer
                return {
                    "ocr_text": sanitized_ocr,
                    "entities": self.extract_regex(sanitized_ocr),
                }

        # No automatic transmission of unsanitized binaries to vision providers.
        return {
            "ocr_text": "", "entities": self.extract_regex(""),
            "error": "Safe local document reading is unavailable. Paste redacted text; external document processing requires a separate consent flow.",
            "processing_status": "LOCAL_READING_UNAVAILABLE",
        }

    @staticmethod
    def _describe_failure(exc: Exception) -> str:
        """
        Turn a Gemini failure into something the person uploading can act on.
        Reporting "set GEMINI_API_KEY" for what is actually a quota error sends
        people to re-check a key that was never the problem.
        """
        text = str(exc)
        if "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
            return (
                "The Gemini free-tier rate limit is currently exhausted (HTTP 429), so the "
                "image could not be read. Wait a minute and retry, or paste the message text."
            )
        if "503" in text or "UNAVAILABLE" in text:
            return (
                "Gemini is temporarily overloaded (HTTP 503) and every fallback model was busy. "
                "Retry shortly, or paste the message text."
            )
        if "timed out" in text.lower() or "timeout" in text.lower():
            return (
                "Reading the document timed out. Try a smaller or clearer image, "
                "or paste the message text."
            )
        if "401" in text or "403" in text or "API key" in text:
            return (
                "Gemini rejected the API key. Check GEMINI_API_KEY in backend/.env "
                "and restart the backend."
            )
        return f"The document could not be read ({text[:160]})."

    def extract(self, text: str) -> ExtractedEntities:
        """
        Synchronous extraction returning ExtractedEntities.
        Preserved for 100% backward compatibility with existing synchronous calls.
        """
        data = self.extract_regex(text)
        return data.to_extracted_entities()

    def extract_regex(self, text: str) -> ExtractedData:
        """
        Deterministic regex/heuristic extraction returning strongly-typed ExtractedData
        backed by the grounded claim extraction parser.
        """
        logger.info("Running deterministic grounded regex extraction on %d chars", len(text))
        result = self.extract_claims(text)
        return result.to_extracted_data()

    # Brand mentions that are about the tooling, not the employer. "Google Meet"
    # in a scam email made every agent investigate Google and return VERIFIED.
    PLATFORM_CONTEXT = [
        r"google\s+meet", r"google\s+form", r"google\s+doc", r"google\s+drive",
        r"google\s+chat", r"google\s+calendar", r"microsoft\s+teams",
        r"google\s+maps", r"amazon\s+web\s+services",
    ]

    def _strip_platform_mentions(self, text: str) -> str:
        cleaned = text
        for pattern in self.PLATFORM_CONTEXT:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
        return cleaned

    # Generic words that show up capitalised in headings but name no employer.
    STOPWORD_COMPANIES = {
        "the", "dear", "subject", "open", "selection", "screening", "domain",
        "technical", "stipend", "best", "date", "time", "mode", "duration",
        "applicant", "candidate", "position", "positions", "round",
    }

    def _detect_company(self, text: str) -> Optional[str]:
        text = self._strip_platform_mentions(text)

        # Check known brands first
        for brand in [
            "Tata Consultancy Services",
            "TCS",
            "Infosys Limited",
            "Infosys",
            "Wipro",
            "Accenture",
            "Google",
            "Microsoft",
            "Amazon",
            "Cognizant",
            "India Post",
        ]:
            if re.search(rf"\b{re.escape(brand)}\b", text, re.IGNORECASE):
                return brand

        # A capitalised name sitting right before a corporate/hiring noun is the
        # strongest generic signal: "Coorix Internship Drive", "Acme Pvt Ltd".
        # Case-sensitive on purpose — see the note on the next pattern.
        match = re.search(
            r"\b([A-Z][A-Za-z0-9&.\-]{1,30}(?:\s+[A-Z][A-Za-z0-9&.\-]{1,30}){0,2})\s+"
            r"(?:Internship|Careers|HR\b|Recruitment|Technologies|Technology|Solutions|"
            r"Softwares?|Systems|Labs|Pvt\.?|Private|Limited|Ltd\.?|Inc\.?|LLP)",
            text,
        )
        if match:
            cand = match.group(1).strip()
            if cand.lower() not in self.STOPWORD_COMPANIES:
                return cand

        # Generic pattern: 'at XYZ' or 'offer from XYZ'.
        # NOT case-insensitive: re.IGNORECASE makes [A-Z] match lowercase too, so
        # this used to return things like "the selection process".
        match = re.search(
            r"(?:\bat|offer from|welcome to|representing)\s+([A-Z][A-Za-z0-9\s&]{2,40})",
            text,
        )
        if match:
            cand = match.group(1).strip()
            cand = re.split(r"\s+\b(?:as|for|to|in|with|role|position)\b", cand, flags=re.IGNORECASE)[0].strip()
            cand = re.sub(r"[\.,;:\n].*$", "", cand).strip()
            if len(cand) >= 2 and cand.lower() not in self.STOPWORD_COMPANIES:
                return cand

        return None

    def _detect_role(self, text: str) -> Optional[str]:
        roles = [
            "Software Development Engineer",
            "Associate Software Engineer",
            "Systems Engineer Specialist",
            "Systems Engineer",
            "Software Engineer",
            "Data Analyst",
            "Business Analyst",
            "Full Stack Developer",
            "Backend Developer",
            "Frontend Developer",
            "Graduate Software Trainee",
            "Graduate Trainee",
            "Customer Support Associate",
            "Operations Executive",
            "Intern",
        ]
        for role in roles:
            if re.search(rf"\b{re.escape(role)}\b", text, re.IGNORECASE):
                return role
        return None

    def _detect_recruiter(self, text: str) -> Optional[str]:
        match = re.search(
            r"(?:Regards|Sincerely|HR Team|Recruiter|From):?[ \t]*\n?[ \t]*([A-Za-z][A-Za-z .]{2,29})",
            text,
        )
        if match:
            name = match.group(1).strip()
            if name.lower() not in ["hr team", "hiring team", "human resources", "recruitment"]:
                return name
        return None

    def _detect_salary(self, text: str):
        # E.g. ₹8 LPA, INR 6,25,000 per annum, 8.5 LPA, INR 15,000 per month
        salary_match = re.search(
            r"(?:INR|Rs\.?|₹|\$)\s*([\d,]+(?:\.\d+)?)\s*(LPA|Lakhs?|per annum|per month|p\.m\.|p\.a\.|CTC)?",
            text,
            re.IGNORECASE,
        )
        if not salary_match:
            salary_match = re.search(r"\b([\d,]+(?:\.\d+)?)\s*(LPA|Lakhs?)\b", text, re.IGNORECASE)

        if not salary_match:
            return None, None, None

        full_salary = salary_match.group(0).strip()
        num_str = salary_match.group(1).replace(",", "")
        period = salary_match.group(2) if len(salary_match.groups()) >= 2 else None

        try:
            amount = float(num_str)
        except ValueError:
            amount = None

        clean_period = None
        if period:
            p_low = period.lower()
            if "lpa" in p_low or "lakh" in p_low:
                clean_period = "LPA"
            elif "month" in p_low or "p.m" in p_low:
                clean_period = "per month"
            elif "annum" in p_low or "p.a" in p_low or "ctc" in p_low:
                clean_period = "per annum"

        return full_salary, amount, clean_period

    def _detect_fee(self, text: str):
        # Look for fee / deposit patterns and extract fee amount + whether it's registration fee
        fee_match = re.search(
            r"(?:(?:pay|deposit|transfer)\s+)?(?:INR|Rs\.?|₹)?\s*([\d,]+)?\s*(?:as\s+)?(security deposit|training fee|laptop charges?|registration fee|processing fee|onboarding fee|screening fee)",
            text,
            re.IGNORECASE,
        )
        if not fee_match:
            fee_match = re.search(
                r"(security deposit|training fee|laptop charges?|registration fee|processing fee|onboarding fee|screening fee)\s*(?:of|:)?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+)",
                text,
                re.IGNORECASE,
            )

        if not fee_match:
            # Fallback for "Pay ₹2500 registration fee"
            pay_match = re.search(r"pay\s*(?:INR|Rs\.?|₹)\s*([\d,]+)\s*(?:registration fee|fee|deposit)", text, re.IGNORECASE)
            if pay_match:
                amount_str = pay_match.group(0).replace("pay", "").strip()
                is_reg = "registration" in pay_match.group(0).lower()
                return amount_str, is_reg
            return None, False

        matched_text = fee_match.group(0).strip()
        # Clean amount string
        amt_match = re.search(r"(?:INR|Rs\.?|₹)?\s*[\d,]+", matched_text, re.IGNORECASE)
        amount_str = amt_match.group(0).strip() if amt_match else matched_text
        is_reg = "registration" in matched_text.lower()
        return amount_str, is_reg

    def _detect_payment_method(self, text: str) -> Optional[str]:
        payment_match = re.search(
            r"\b(UPI|Google Pay|GPay|PhonePe|Paytm|QR Code|NEFT|cryptocurrency|Telegram|WhatsApp)\b",
            text,
            re.IGNORECASE,
        )
        return payment_match.group(0) if payment_match else None

    def _detect_website(self, text: str) -> Optional[str]:
        match = re.search(r"https?://(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?", text)
        return match.group(0) if match else None

    def _detect_address(self, text: str) -> Optional[str]:
        match = re.search(r"(?:Location|Address|Report to):\s*([A-Za-z0-9\s,.-]{5,50})", text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    def _detect_joining_date(self, text: str) -> Optional[str]:
        match = re.search(r"(?:joining on|reporting date|report to the .* on|joining date:?)\s*([A-Za-z0-9,\s]{4,25})", text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    # Mime types whose bytes carry no readable text without a real parser or a
    # vision model. Scraping printable fragments out of them used to yield things
    # like company "BQC" and salary "$1" from PDF stream internals — a confident
    # verdict computed from noise, which is worse than refusing to read the file.
    OPAQUE_MIME_PREFIXES = ("image/", "application/pdf")

    def _fallback_text_extract(self, file_bytes: bytes, mime_type: str) -> str:
        """
        Best-effort text extraction for documents when Gemini vision is unavailable.
        Returns "" when the format cannot be read without it, so the caller can say
        so plainly instead of analysing garbage.
        """
        normalized = (mime_type or "").lower().split(";")[0].strip()
        if normalized.startswith(self.OPAQUE_MIME_PREFIXES):
            logger.warning(
                "Cannot read %s: no vision provider succeeded (Groq and Gemini unset or failed).",
                normalized,
            )
            return ""

        try:
            decoded = file_bytes.decode("utf-8", errors="ignore")
            printable = "".join(ch for ch in decoded if ch.isprintable() or ch in "\n\r\t")
            if len(printable.strip()) > 20:
                return printable.strip()
        except Exception:
            pass

        return ""
