import re
from typing import Optional, Dict, Any, List
from app.schemas.analysis import ExtractedEntities, ExtractedData
from app.services.ai.gemini_client import GeminiClient
from app.core.logging import logger


class EntityExtractor:
    """
    Extracts key entities from offer letters, screenshots, recruiter messages, or emails.
    Primary pipeline: Gemini 2.5 Flash structured entity extraction & multimodal OCR.
    Fallback pipeline: Robust deterministic regex/heuristic extraction.
    """

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self.gemini_client = gemini_client or GeminiClient()

    async def extract_entities(self, text: str) -> ExtractedData:
        """
        Extracts structured ExtractedData from text using Gemini with automatic regex fallback.
        Handles timeout, invalid JSON, rate limit, and API errors transparently.
        """
        if self.gemini_client and self.gemini_client.api_key:
            try:
                logger.info("Attempting Gemini entity extraction (%d chars)", len(text))
                return await self.gemini_client.extract_entities(text)
            except Exception as e:
                logger.warning("Gemini extraction failed (%s). Falling back to regex extractor.", str(e))

        logger.info("Using regex extraction pipeline")
        return self.extract_regex(text)

    async def extract_from_document(self, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        """
        Extracts text (OCR) and structured entities from PDF or image documents.
        Uses Gemini multimodal vision with fallback to local text parsing.
        Returns:
            {
                "ocr_text": str,
                "entities": ExtractedData
            }
        """
        if self.gemini_client and self.gemini_client.api_key:
            try:
                logger.info("Attempting Gemini document extraction (%s, %d bytes)", mime_type, len(file_bytes))
                return await self.gemini_client.extract_from_document(file_bytes, mime_type)
            except Exception as e:
                logger.warning("Gemini document extraction failed (%s). Falling back to local text parsing.", str(e))

        ocr_text = self._fallback_text_extract(file_bytes, mime_type)
        entities = self.extract_regex(ocr_text)
        return {
            "ocr_text": ocr_text,
            "entities": entities,
        }

    def extract(self, text: str) -> ExtractedEntities:
        """
        Synchronous extraction returning ExtractedEntities.
        Preserved for 100% backward compatibility with existing synchronous calls.
        """
        data = self.extract_regex(text)
        return data.to_extracted_entities()

    def extract_regex(self, text: str) -> ExtractedData:
        """
        Deterministic regex/heuristic extraction returning strongly-typed ExtractedData.
        """
        logger.info("Running deterministic regex extraction on %d chars", len(text))

        # Email regex
        email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
        recruiter_email = email_match.group(0).rstrip(".,;:)") if email_match else None

        # Phone regex (Indian format standard)
        phone_match = re.search(r"(?:\+91[\-\s]?)?[6789]\d{9}", text)
        recruiter_phone = phone_match.group(0) if phone_match else None

        # Company detection
        company_name = self._detect_company(text)

        # Role detection
        job_role = self._detect_role(text)

        # Recruiter name detection
        recruiter_name = self._detect_recruiter(text)

        # Salary detection
        salary_str, salary_amount, salary_period = self._detect_salary(text)

        # Fee or deposit detection
        demanded_fee, is_reg_fee = self._detect_fee(text)

        # Payment method detection
        payment_method = self._detect_payment_method(text)

        # Website & Address detection
        website = self._detect_website(text)
        address = self._detect_address(text)

        # Joining date detection
        joining_date = self._detect_joining_date(text)

        payment_request_detected = bool(demanded_fee)

        # Flags identified
        flags: List[str] = []
        if payment_request_detected:
            flags.append("DEMANDS_UPFRONT_FEE")
            if is_reg_fee:
                flags.append("REGISTRATION_FEE_REQUESTED")

        if payment_method and payment_method.upper() in ["UPI", "GPAY", "PHONEPE", "PAYTM"]:
            flags.append("UPI_PAYMENT_REQUESTED")

        if recruiter_email:
            free_domains = ["gmail.com", "outlook.com", "yahoo.com", "hotmail.com"]
            domain = recruiter_email.split("@")[-1].lower() if "@" in recruiter_email else ""
            if domain in free_domains:
                flags.append("PUBLIC_EMAIL_DOMAIN_USED")

        if "telegram" in text.lower():
            flags.append("TELEGRAM_CONTACT_SUSPICIOUS")

        return ExtractedData(
            company=company_name,
            recruiter_name=recruiter_name,
            recruiter_email=recruiter_email,
            recruiter_phone=recruiter_phone,
            job_role=job_role,
            salary=salary_str,
            salary_amount=salary_amount,
            salary_period=salary_period,
            joining_date=joining_date,
            address=address,
            website=website,
            payment_request_detected=payment_request_detected,
            payment_amount=demanded_fee,
            payment_method=payment_method,
            flags=flags,
            raw_text=text,
        )

    def _detect_company(self, text: str) -> Optional[str]:
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

        # Generic pattern: 'at XYZ' or 'offer from XYZ'
        match = re.search(
            r"(?:at|offer from|welcome to|representing)\s+([A-Z][A-Za-z0-9\s&]{2,40})",
            text,
            re.IGNORECASE,
        )
        if match:
            cand = match.group(1).strip()
            cand = re.split(r"\s+\b(?:as|for|to|in|with|role|position)\b", cand, flags=re.IGNORECASE)[0].strip()
            cand = re.sub(r"[\.,;:\n].*$", "", cand).strip()
            if len(cand) >= 2:
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
        match = re.search(r"(?:Regards|Sincerely|HR Team|Recruiter|From):\s*([A-Za-z\s]{3,30})", text)
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

    def _fallback_text_extract(self, file_bytes: bytes, mime_type: str) -> str:
        """Simple text extraction fallback for documents when Gemini is not active."""
        try:
            decoded = file_bytes.decode("utf-8", errors="ignore")
            printable = "".join(ch for ch in decoded if ch.isprintable() or ch in "\n\r\t")
            if len(printable.strip()) > 20:
                return printable.strip()
        except Exception:
            pass

        # For binary PDF files, extract printable string fragments
        text_content = file_bytes.decode("latin-1", errors="ignore")
        matches = re.findall(r"[A-Za-z0-9@_.\-:\s,₹$]{4,}", text_content)
        extracted = " ".join(m.strip() for m in matches[:50] if len(m.strip()) > 3)
        return extracted or f"Document upload ({mime_type}, {len(file_bytes)} bytes)"
