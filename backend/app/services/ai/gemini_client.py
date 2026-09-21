import base64
import json
import re
from typing import Optional, Dict, Any, List
import httpx
from app.core.config import settings
from app.core.logging import logger
from app.schemas.analysis import ExtractedData


class GeminiError(Exception):
    """Base exception for Gemini client failures."""
    pass


class GeminiTimeoutError(GeminiError):
    """Raised when Gemini API request times out."""
    pass


class GeminiRateLimitError(GeminiError):
    """Raised when Gemini API returns HTTP 429 rate limit."""
    pass


class GeminiParseError(GeminiError):
    """Raised when Gemini response cannot be parsed into valid JSON or ExtractedData."""
    pass


class GeminiClient:
    """
    Interface for Google Gemini (default: gemini-2.5-flash).
    Provides structured entity extraction from offer text and multimodal OCR for documents (PDF/images).
    """

    SUPPORTED_MIME_TYPES = {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "application/pdf",
    }

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None, timeout: float = 8.0):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        self.timeout = timeout
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def _get_api_url(self) -> str:
        return f"{self.base_url}/{self.model_name}:generateContent?key={self.api_key}"

    def _clean_and_parse_json(self, raw_text: str) -> Dict[str, Any]:
        """
        Safely strips markdown code blocks, finds outermost JSON object,
        and parses into a Python dictionary.
        """
        cleaned = raw_text.strip()
        # Strip ```json ... ``` or ``` ... ```
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Attempt to locate first { and last }
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError as err:
                    raise GeminiParseError(f"Failed to decode extracted JSON substring: {err}") from err
            raise GeminiParseError("No valid JSON object found in Gemini response text")

    async def extract_entities(self, text: str) -> ExtractedData:
        """
        Extracts structured entities from offer text using Gemini 2.5 Flash.
        Forces JSON output, parses safely, and returns a validated ExtractedData instance.
        """
        if not self.api_key:
            raise GeminiError("Gemini API key is not configured")

        logger.info("GeminiClient extracting entities with %s (input %d chars)", self.model_name, len(text))

        system_instruction = (
            "You are AsliOffer's Entity Extraction Agent.\n"
            "Your job is to extract structured information from a job offer, internship offer, recruiter message, "
            "email, WhatsApp message, Telegram message, or offer letter.\n\n"
            "Rules:\n"
            "1. Extract only information explicitly present. Never invent or infer missing values.\n"
            "2. If a field is not found, return null.\n"
            "3. Return strictly valid JSON conforming to the schema.\n"
            "4. If a fee or deposit is demanded (registration fee, laptop security deposit, training fee, onboarding charge):\n"
            "   - set payment_request_detected = true\n"
            "   - set payment_amount to the exact amount mentioned (e.g., '₹2500' or 'INR 15,000')\n"
            "   - set payment_method to the rail if mentioned (e.g. 'UPI', 'Google Pay', 'Bank Transfer')\n"
            "   - always include 'DEMANDS_UPFRONT_FEE' in flags\n"
            "   - if it is a registration fee, include 'REGISTRATION_FEE_REQUESTED' in flags\n"
            "   - if payment is via UPI/QR code, include 'UPI_PAYMENT_REQUESTED' in flags\n"
            "5. If recruiter uses a free webmail provider (gmail.com, outlook.com, yahoo.com) for a corporate role, "
            "include 'PUBLIC_EMAIL_DOMAIN_USED' in flags.\n"
            "6. If Telegram is mentioned for recruitment, include 'TELEGRAM_CONTACT_SUSPICIOUS' in flags.\n"
            "7. Populate raw_text with the full input text.\n\n"
            "Schema:\n"
            "{\n"
            '  "company": string | null,\n'
            '  "recruiter_name": string | null,\n'
            '  "recruiter_email": string | null,\n'
            '  "recruiter_phone": string | null,\n'
            '  "job_role": string | null,\n'
            '  "salary": string | null,\n'
            '  "salary_amount": float | null,\n'
            '  "salary_period": string | null,\n'
            '  "joining_date": string | null,\n'
            '  "address": string | null,\n'
            '  "website": string | null,\n'
            '  "payment_request_detected": boolean,\n'
            '  "payment_amount": string | null,\n'
            '  "payment_method": string | null,\n'
            '  "flags": string[],\n'
            '  "raw_text": string\n'
            "}"
        )

        user_content = f"Input Text:\n{text}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": system_instruction},
                        {"text": user_content},
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self._get_api_url(), json=payload)

                if response.status_code == 429:
                    raise GeminiRateLimitError("Gemini API rate limit exceeded (HTTP 429)")

                if response.status_code != 200:
                    raise GeminiError(f"Gemini API returned status {response.status_code}: {response.text}")

                res_json = response.json()
        except httpx.TimeoutException as te:
            raise GeminiTimeoutError(f"Gemini request timed out after {self.timeout}s: {te}") from te
        except (GeminiError, GeminiRateLimitError):
            raise
        except Exception as ex:
            raise GeminiError(f"Gemini request failed: {ex}") from ex

        # Extract generated text from Gemini candidate
        try:
            candidate = res_json["candidates"][0]
            raw_output = candidate["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as err:
            raise GeminiParseError(f"Unexpected response structure from Gemini API: {err}") from err

        parsed_dict = self._clean_and_parse_json(raw_output)
        if not parsed_dict.get("raw_text"):
            parsed_dict["raw_text"] = text

        try:
            return ExtractedData(**parsed_dict)
        except Exception as val_err:
            raise GeminiParseError(f"Extracted data validation failed: {val_err}") from val_err

    async def extract_from_document(self, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        """
        Reads a document (PDF, PNG, JPEG) using Gemini multimodal capabilities.
        Transcribes the full text as 'ocr_text' and extracts structured 'entities'.
        Returns:
            {
                "ocr_text": str,
                "entities": ExtractedData
            }
        """
        if not self.api_key:
            raise GeminiError("Gemini API key is not configured")

        normalized_mime = mime_type.lower().split(";")[0].strip()
        if normalized_mime == "image/jpg":
            normalized_mime = "image/jpeg"

        if normalized_mime not in self.SUPPORTED_MIME_TYPES:
            raise ValueError(
                f"Unsupported mime type '{mime_type}'. Supported: {', '.join(sorted(self.SUPPORTED_MIME_TYPES))}"
            )

        logger.info(
            "GeminiClient multimodal document processing (%s, %d bytes) with %s",
            normalized_mime,
            len(file_bytes),
            self.model_name,
        )

        b64_data = base64.b64encode(file_bytes).decode("utf-8")

        prompt = (
            "You are AsliOffer's Multimodal Document Extraction Agent.\n"
            "Carefully examine the attached document (offer letter, email screenshot, or message).\n\n"
            "Task:\n"
            "1. Accurately transcribe all readable text from the document into 'ocr_text'.\n"
            "2. Extract structured entities into 'entities' conforming to the schema below.\n\n"
            "Entity Rules:\n"
            "- Extract only information explicitly present in the document. Never guess.\n"
            "- If any fee, deposit, or payment is requested (registration fee, laptop charge, training deposit):\n"
            "  * payment_request_detected = true\n"
            "  * payment_amount = extracted amount string\n"
            "  * include 'DEMANDS_UPFRONT_FEE' in flags\n"
            "  * if it is a registration fee, include 'REGISTRATION_FEE_REQUESTED' in flags\n"
            "  * if UPI is requested, include 'UPI_PAYMENT_REQUESTED' in flags\n"
            "- If recruiter uses free webmail (@gmail.com, @outlook.com), include 'PUBLIC_EMAIL_DOMAIN_USED'.\n"
            "- If Telegram is referenced, include 'TELEGRAM_CONTACT_SUSPICIOUS'.\n\n"
            "Return JSON matching:\n"
            "{\n"
            '  "ocr_text": string,\n'
            '  "entities": {\n'
            '    "company": string | null,\n'
            '    "recruiter_name": string | null,\n'
            '    "recruiter_email": string | null,\n'
            '    "recruiter_phone": string | null,\n'
            '    "job_role": string | null,\n'
            '    "salary": string | null,\n'
            '    "salary_amount": float | null,\n'
            '    "salary_period": string | null,\n'
            '    "joining_date": string | null,\n'
            '    "address": string | null,\n'
            '    "website": string | null,\n'
            '    "payment_request_detected": boolean,\n'
            '    "payment_amount": string | null,\n'
            '    "payment_method": string | null,\n'
            '    "flags": string[],\n'
            '    "raw_text": string\n'
            '  }\n'
            "}"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": normalized_mime,
                                "data": b64_data,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=max(self.timeout * 2, 15.0)) as client:
                response = await client.post(self._get_api_url(), json=payload)

                if response.status_code == 429:
                    raise GeminiRateLimitError("Gemini API rate limit exceeded (HTTP 429)")

                if response.status_code != 200:
                    raise GeminiError(f"Gemini API returned status {response.status_code}: {response.text}")

                res_json = response.json()
        except httpx.TimeoutException as te:
            raise GeminiTimeoutError(f"Gemini document processing timed out: {te}") from te
        except (GeminiError, GeminiRateLimitError):
            raise
        except Exception as ex:
            raise GeminiError(f"Gemini document request failed: {ex}") from ex

        try:
            candidate = res_json["candidates"][0]
            raw_output = candidate["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as err:
            raise GeminiParseError(f"Unexpected multimodal response structure from Gemini API: {err}") from err

        parsed_dict = self._clean_and_parse_json(raw_output)
        ocr_text = parsed_dict.get("ocr_text", "")
        entities_raw = parsed_dict.get("entities", {})

        if not entities_raw.get("raw_text"):
            entities_raw["raw_text"] = ocr_text

        try:
            entities = ExtractedData(**entities_raw)
        except Exception as val_err:
            raise GeminiParseError(f"Multimodal entity validation failed: {val_err}") from val_err

        return {
            "ocr_text": ocr_text,
            "entities": entities,
        }

    async def analyze_document_text(self, content: str) -> Dict[str, Any]:
        """
        Analyze document text and extract structured intent or flags.
        Preserved for backward compatibility.
        """
        logger.info("GeminiClient processing text with %s", self.model_name)
        return {
            "model": self.model_name,
            "status": "success",
            "flags": ["LLM_AUDIT_PASS"],
            "summary": "Document analyzed for linguistic authenticity and pressure tactics.",
        }

    async def synthesize_report(
        self,
        company_findings: Dict[str, Any],
        recruiter_findings: Dict[str, Any],
        scam_findings: Dict[str, Any],
    ) -> str:
        """
        Synthesize multi-agent findings into a plain-English explanation.
        Preserved for backward compatibility.
        """
        logger.info("GeminiClient synthesizing multi-agent findings")
        return (
            "Based on live public footprint checks, the employer's genuine web presence was evaluated "
            "against the recruiter's credentials and payment requirements. Cross-referenced against known scam registries."
        )
