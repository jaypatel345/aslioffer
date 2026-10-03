"""
Groq vision client for reading offer letters supplied as PDFs or screenshots.

Groq sits in front of Gemini because its free tier (30 requests/minute,
1000/day) is far more forgiving than Gemini's, which exhausted every model in
the fallback chain on a single screenshot upload. The interface deliberately
mirrors GeminiClient.extract_from_document so EntityExtractor can try one and
then the other without special-casing either.
"""

import base64
import json
import re
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.schemas.analysis import ExtractedData


class GroqError(Exception):
    """Base error for Groq interactions."""


class GroqTimeoutError(GroqError):
    """Raised when the Groq request exceeds its deadline."""


class GroqRateLimitError(GroqError):
    """Raised on HTTP 429."""


class GroqParseError(GroqError):
    """Raised when the response is not the JSON contract we asked for."""


class GroqClient:
    # Groq's documented limits for the vision model: 20MB per image, 3 images
    # per request. We only ever send one.
    MAX_IMAGE_BYTES = 20 * 1024 * 1024

    # PDFs are not accepted as image_url content; only rasterised formats are.
    SUPPORTED_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

    RETRY_STATUSES = (429, 500, 502, 503)
    MAX_ATTEMPTS = 2

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: float = 45.0,
    ):
        self.api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self.model_name = model_name or settings.GROQ_MODEL
        self.timeout = timeout
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    # Shared with the Gemini prompt so both providers return the same shape.
    PROMPT = (
        "You are AsliOffer's Multimodal Document Extraction Agent.\n"
        "Carefully examine the attached document (offer letter, email screenshot, or message).\n\n"
        "Task:\n"
        "1. Accurately transcribe all readable text from the document into 'ocr_text'.\n"
        "2. Extract structured entities into 'entities' conforming to the schema below.\n\n"
        "Entity Rules:\n"
        "- Extract only information explicitly present in the document. Never guess.\n"
        "- 'company' is the EMPLOYER. Never return a meeting or tool platform named in the\n"
        "  text (Google Meet, Microsoft Teams, Zoom) as the employer.\n"
        "- If any fee, deposit, or payment is requested (registration fee, laptop charge, training deposit):\n"
        "  * payment_request_detected = true\n"
        "  * payment_amount = extracted amount string\n"
        "  * include 'DEMANDS_UPFRONT_FEE' in flags\n"
        "  * if it is a registration fee, include 'REGISTRATION_FEE_REQUESTED' in flags\n"
        "  * if UPI is requested, include 'UPI_PAYMENT_REQUESTED' in flags\n"
        "- If recruiter uses free webmail (@gmail.com, @outlook.com), include 'PUBLIC_EMAIL_DOMAIN_USED'.\n"
        "- If Telegram is referenced, include 'TELEGRAM_CONTACT_SUSPICIOUS'.\n\n"
        "Respond with JSON only, matching:\n"
        "{\n"
        '  "ocr_text": string,\n'
        '  "entities": {\n'
        '    "company": string | null,\n'
        '    "recruiter_name": string | null,\n'
        '    "recruiter_email": string | null,\n'
        '    "recruiter_phone": string | null,\n'
        '    "job_role": string | null,\n'
        '    "salary": string | null,\n'
        '    "salary_amount": number | null,\n'
        '    "salary_period": string | null,\n'
        '    "joining_date": string | null,\n'
        '    "address": string | null,\n'
        '    "website": string | null,\n'
        '    "payment_request_detected": boolean,\n'
        '    "payment_amount": string | null,\n'
        '    "payment_method": string | null,\n'
        '    "flags": [string],\n'
        '    "raw_text": string\n'
        "  }\n"
        "}"
    )

    def _clean_and_parse_json(self, raw_text: str) -> Dict[str, Any]:
        """Strip markdown fences some models wrap JSON in, then parse."""
        text = raw_text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Fall back to the outermost object if the model added prose.
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise GroqParseError(f"Groq returned non-JSON output: {text[:200]}")
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as err:
                raise GroqParseError(f"Groq returned malformed JSON: {err}") from err

    async def _post_with_retry(self, payload: dict) -> httpx.Response:
        last: Optional[httpx.Response] = None
        for attempt in range(self.MAX_ATTEMPTS):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.base_url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
            if response.status_code not in self.RETRY_STATUSES:
                return response
            last = response
            if attempt < self.MAX_ATTEMPTS - 1:
                logger.warning(
                    "Groq %s returned %d (attempt %d/%d); retrying",
                    self.model_name, response.status_code, attempt + 1, self.MAX_ATTEMPTS,
                )
        return last

    async def extract_from_document(self, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        """
        Read a screenshot and return {"ocr_text": str, "entities": ExtractedData},
        matching GeminiClient.extract_from_document exactly.
        """
        if not self.api_key:
            raise GroqError("Groq API key is not configured")

        normalized_mime = (mime_type or "").lower().split(";")[0].strip()
        if normalized_mime == "image/jpg":
            normalized_mime = "image/jpeg"

        if normalized_mime not in self.SUPPORTED_MIME_TYPES:
            raise ValueError(
                f"Groq vision does not accept '{mime_type}'. "
                f"Supported: {', '.join(sorted(self.SUPPORTED_MIME_TYPES))}"
            )

        if len(file_bytes) > self.MAX_IMAGE_BYTES:
            raise ValueError(
                f"Image is {len(file_bytes) // (1024 * 1024)}MB; Groq accepts at most 20MB."
            )

        logger.info(
            "GroqClient vision processing (%s, %d bytes) with %s",
            normalized_mime, len(file_bytes), self.model_name,
        )

        b64_data = base64.b64encode(file_bytes).decode("utf-8")
        payload = {
            "model": self.model_name,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{normalized_mime};base64,{b64_data}"},
                        },
                    ],
                }
            ],
        }

        try:
            response = await self._post_with_retry(payload)
            if response.status_code == 429:
                raise GroqRateLimitError("Groq API rate limit exceeded (HTTP 429)")
            if response.status_code != 200:
                raise GroqError(f"Groq API returned status {response.status_code}: {response.text[:300]}")
            res_json = response.json()
        except httpx.TimeoutException as te:
            raise GroqTimeoutError(f"Groq document processing timed out after {self.timeout}s: {te}") from te
        except (GroqError, GroqRateLimitError):
            raise
        except Exception as ex:
            raise GroqError(f"Groq document request failed: {ex}") from ex

        try:
            raw_output = res_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as err:
            raise GroqParseError(f"Unexpected response structure from Groq API: {err}") from err

        parsed = self._clean_and_parse_json(raw_output)
        ocr_text = parsed.get("ocr_text", "") or ""
        entities_raw = parsed.get("entities") or {}

        if not entities_raw.get("raw_text"):
            entities_raw["raw_text"] = ocr_text

        try:
            entities = ExtractedData(**entities_raw)
        except Exception as val_err:
            raise GroqParseError(f"Groq entity validation failed: {val_err}") from val_err

        return {"ocr_text": ocr_text, "entities": entities}
