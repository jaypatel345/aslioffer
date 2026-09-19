import re
from typing import Optional
from app.schemas.analysis import ExtractedEntities
from app.core.logging import logger


class EntityExtractor:
    """
    Extracts key entities from offer letters, screenshots, recruiter messages, or emails.
    Supports heuristic extraction with future expansion to Gemini 2.5 Flash multimodal vision & NLP.
    """

    def extract(self, text: str) -> ExtractedEntities:
        logger.info("Extracting entities from offer content (%d chars)", len(text))

        # Email regex
        email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
        recruiter_email = email_match.group(0) if email_match else None

        # Phone regex (Indian format standard)
        phone_match = re.search(r"(?:\+91[\-\s]?)?[6789]\d{9}", text)
        recruiter_phone = phone_match.group(0) if phone_match else None

        # Company detection (Heuristics / keywords)
        company_name = self._detect_company(text)

        # Salary / CTC detection
        salary_match = re.search(
            r"(?:INR|Rs\.?|₹|\$)\s*[\d,]+(?:\s*(?:LPA|per annum|per month|p\.m\.|p\.a\.|CTC))?",
            text,
            re.IGNORECASE,
        )
        if not salary_match:
            salary_match = re.search(r"\b\d+(?:\.\d+)?\s*(?:LPA|Lakhs?)\b", text, re.IGNORECASE)
        offered_salary = salary_match.group(0) if salary_match else None

        # Fee or deposit detection (Scam red flags)
        fee_match = re.search(
            r"(?:security deposit|training fee|laptop charges?|registration fee|processing fee|onboarding fee)\s*(?:of|:)?\s*(?:INR|Rs\.?|₹)?\s*[\d,]+",
            text,
            re.IGNORECASE,
        )
        demanded_fee = fee_match.group(0) if fee_match else None

        # Payment method detection
        payment_match = re.search(
            r"(?:UPI|Google Pay|GPay|PhonePe|Paytm|QR Code|NEFT|cryptocurrency|Telegram|WhatsApp)",
            text,
            re.IGNORECASE,
        )
        payment_method = payment_match.group(0) if payment_match else None

        # Flags identified
        flags = []
        if demanded_fee:
            flags.append("DEMANDS_UPFRONT_FEE")
        if recruiter_email and ("gmail.com" in recruiter_email.lower() or "outlook.com" in recruiter_email.lower() or "yahoo.com" in recruiter_email.lower()):
            flags.append("PUBLIC_EMAIL_DOMAIN_USED")
        if "telegram" in text.lower():
            flags.append("TELEGRAM_CONTACT_SUSPICIOUS")

        # Role heuristics
        role_title = self._detect_role(text)

        # Recruiter name heuristics
        recruiter_name = self._detect_recruiter(text)

        return ExtractedEntities(
            company_name=company_name or "Unknown Company",
            recruiter_name=recruiter_name,
            recruiter_email=recruiter_email,
            recruiter_phone=recruiter_phone,
            role_title=role_title or "Position Not Specified",
            offered_salary=offered_salary,
            location="Remote / India",
            demanded_fee=demanded_fee,
            payment_method=payment_method,
            flags=flags,
        )

    def _detect_company(self, text: str) -> Optional[str]:
        # Known companies or pattern 'at XYZ Corp'
        match = re.search(
            r"(?:at|offer from|welcome to|representing)\s+([A-Z][A-Za-z0-9\s&]{2,30}(?:Ltd|Limited|Inc|Technologies|Solutions|Services|Private Limited|Pvt Ltd)?)",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
        # Common tech names
        for brand in ["Tata Consultancy Services", "TCS", "Infosys", "Wipro", "Accenture", "Google", "Microsoft", "Amazon", "Cognizant", "India Post"]:
            if brand.lower() in text.lower():
                return brand
        return None

    def _detect_role(self, text: str) -> Optional[str]:
        roles = [
            "Software Development Engineer",
            "Software Engineer",
            "Data Analyst",
            "Business Analyst",
            "Full Stack Developer",
            "Backend Developer",
            "Frontend Developer",
            "Graduate Trainee",
            "Customer Support Associate",
            "Operations Executive",
            "Intern",
        ]
        for role in roles:
            if role.lower() in text.lower():
                return role
        return None

    def _detect_recruiter(self, text: str) -> Optional[str]:
        match = re.search(r"(?:Regards|Sincerely|HR Team|Recruiter|From):\s*([A-Za-z\s]{3,30})", text)
        if match:
            name = match.group(1).strip()
            if name.lower() not in ["hr team", "hiring team", "human resources", "recruitment"]:
                return name
        return None
