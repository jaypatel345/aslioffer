import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from app.schemas.analysis import ExtractedData
from app.services.ai.gemini_client import (
    GeminiClient,
    GeminiError,
    GeminiTimeoutError,
    GeminiParseError,
    GeminiRateLimitError,
)
from app.services.extractor.entity_extractor import EntityExtractor


@pytest.fixture
def entity_extractor():
    return EntityExtractor(gemini_client=GeminiClient(api_key=""))


@pytest.fixture
def mock_gemini_client():
    client = GeminiClient(api_key="mock-api-key-test")
    return client


# ---------------------------------------------------------------------------
# 1. Acceptance Criteria & Genuine / Scam Tests (Regex Fallback & Core Logic)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_acceptance_criteria_genuine_offer(entity_extractor):
    """
    Acceptance Criteria 1:
    Input: "Congratulations. You have been selected for Software Engineer at Infosys. Package ₹8 LPA. Contact hr@infosys.com"
    Output: company == 'Infosys', recruiter_email == 'hr@infosys.com', job_role == 'Software Engineer', etc.
    """
    text = "Congratulations. You have been selected for Software Engineer at Infosys. Package ₹8 LPA. Contact hr@infosys.com"
    data = await entity_extractor.extract_entities(text)

    assert isinstance(data, ExtractedData)
    assert data.company == "Infosys"
    assert data.recruiter_email == "hr@infosys.com"
    assert data.job_role == "Software Engineer"
    assert data.salary == "₹8 LPA"
    assert data.salary_amount == 8.0
    assert data.salary_period == "LPA"
    assert not data.payment_request_detected


@pytest.mark.asyncio
async def test_acceptance_criteria_scam_offer(entity_extractor):
    """
    Acceptance Criteria 2:
    Input: "Pay ₹2500 registration fee via UPI before joining."
    Output flags include: ['REGISTRATION_FEE_REQUESTED', 'UPI_PAYMENT_REQUESTED']
    """
    text = "Pay ₹2500 registration fee via UPI before joining."
    data = await entity_extractor.extract_entities(text)

    assert isinstance(data, ExtractedData)
    assert data.payment_request_detected is True
    assert "₹2500" in (data.payment_amount or "")
    assert data.payment_method == "UPI"
    assert "REGISTRATION_FEE_REQUESTED" in data.flags
    assert "UPI_PAYMENT_REQUESTED" in data.flags
    assert "DEMANDS_UPFRONT_FEE" in data.flags


@pytest.mark.asyncio
async def test_missing_fields_graceful_handling(entity_extractor):
    """Test text with almost no identifiable entities produces clean nulls and no crash."""
    sparse_text = "Hello, please find the document attached for your perusal."
    data = await entity_extractor.extract_entities(sparse_text)

    assert isinstance(data, ExtractedData)
    assert data.company is None
    assert data.recruiter_email is None
    assert data.recruiter_phone is None
    assert data.salary is None
    assert data.payment_request_detected is False
    assert data.raw_text == sparse_text


@pytest.mark.asyncio
async def test_adapter_to_extracted_entities(entity_extractor):
    """Verify to_extracted_entities adapter creates backward-compatible model."""
    text = (
        "Congratulations from Tata Consultancy Services. Offer for Associate Software Engineer. "
        "Package INR 8.5 LPA. Deposit INR 15,000 security deposit via UPI. Contact rohit.tcs@gmail.com."
    )
    data = await entity_extractor.extract_entities(text)
    entities = data.to_extracted_entities()

    assert entities.company_name == "Tata Consultancy Services"
    assert entities.role_title == "Associate Software Engineer"
    assert entities.demanded_fee is not None and "15,000" in entities.demanded_fee
    assert entities.payment_method == "UPI"
    assert "PUBLIC_EMAIL_DOMAIN_USED" in entities.flags


# ---------------------------------------------------------------------------
# 2. Gemini Live Call Mocking: Success, JSON parsing, and Errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gemini_client_success(mock_gemini_client):
    """Verify GeminiClient correctly parses a valid JSON response from Gemini API."""
    gemini_response_json = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "company": "Wipro",
                                "recruiter_name": "Anita Roy",
                                "recruiter_email": "anita@wipro.com",
                                "recruiter_phone": "+91 9876543210",
                                "job_role": "Backend Developer",
                                "salary": "₹7.5 LPA",
                                "salary_amount": 7.5,
                                "salary_period": "LPA",
                                "joining_date": "2026-08-01",
                                "address": "Electronic City, Bangalore",
                                "website": "https://www.wipro.com",
                                "payment_request_detected": False,
                                "payment_amount": None,
                                "payment_method": None,
                                "flags": [],
                                "raw_text": "Sample text",
                            })
                        }
                    ]
                }
            }
        ]
    }

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = gemini_response_json

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        extracted = await mock_gemini_client.extract_entities("Sample text")
        assert extracted.company == "Wipro"
        assert extracted.job_role == "Backend Developer"
        assert extracted.recruiter_email == "anita@wipro.com"
        assert extracted.salary_amount == 7.5


@pytest.mark.asyncio
async def test_gemini_client_parses_markdown_code_block(mock_gemini_client):
    """Ensure ```json fences are automatically stripped and parsed cleanly."""
    markdown_wrapped_text = """```json
    {
      "company": "Google",
      "recruiter_name": "Sundar",
      "recruiter_email": "sundar@google.com",
      "recruiter_phone": null,
      "job_role": "Software Engineer",
      "salary": "₹45 LPA",
      "salary_amount": 45.0,
      "salary_period": "LPA",
      "joining_date": null,
      "address": "Hyderabad",
      "website": "https://google.com",
      "payment_request_detected": false,
      "payment_amount": null,
      "payment_method": null,
      "flags": [],
      "raw_text": "text"
    }
    ```"""

    gemini_response_json = {
        "candidates": [{"content": {"parts": [{"text": markdown_wrapped_text}]}}]
    }

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = gemini_response_json

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        extracted = await mock_gemini_client.extract_entities("text")
        assert extracted.company == "Google"
        assert extracted.salary_amount == 45.0


# ---------------------------------------------------------------------------
# 3. Fallback Tests: Invalid JSON, Timeout, and Rate Limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_on_invalid_gemini_json():
    """If Gemini returns garbage or malformed JSON, entity extractor falls back to regex."""
    malformed_response = {
        "candidates": [{"content": {"parts": [{"text": "I am an AI and here is your data: {not valid json!}"}]}}]
    }

    mock_client = GeminiClient(api_key="valid-key")
    extractor = EntityExtractor(gemini_client=mock_client)

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = malformed_response

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        text = "Congratulations on your selection at Infosys as Systems Engineer. CTC: ₹6.5 LPA."
        extracted = await extractor.extract_entities(text)

        # Fallback executed without throwing
        assert isinstance(extracted, ExtractedData)
        assert extracted.company == "Infosys"
        assert extracted.job_role == "Systems Engineer"


@pytest.mark.asyncio
async def test_fallback_on_gemini_timeout():
    """If Gemini times out, entity extractor catches the timeout and falls back to regex."""
    mock_client = GeminiClient(api_key="valid-key", timeout=0.01)
    extractor = EntityExtractor(gemini_client=mock_client)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Read timed out")

        text = "Offer from Tata Consultancy Services for Graduate Trainee. Salary INR 4.5 LPA."
        extracted = await extractor.extract_entities(text)

        # Fallback executed successfully
        assert isinstance(extracted, ExtractedData)
        assert extracted.company == "Tata Consultancy Services"
        assert extracted.job_role == "Graduate Trainee"


@pytest.mark.asyncio
async def test_fallback_on_gemini_rate_limit_429():
    """If Gemini returns 429 Too Many Requests, extractor falls back to regex."""
    mock_client = GeminiClient(api_key="valid-key")
    extractor = EntityExtractor(gemini_client=mock_client)

    mock_response = MagicMock(status_code=429, text="Resource has been exhausted")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        text = "Pay ₹2500 registration fee via UPI before joining."
        extracted = await extractor.extract_entities(text)

        assert extracted.payment_request_detected is True
        assert "REGISTRATION_FEE_REQUESTED" in extracted.flags


# ---------------------------------------------------------------------------
# 4. Multimodal Document OCR Flow Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_document_ocr_flow_with_mock_gemini(mock_gemini_client):
    """Test extract_from_document with PDF / image bytes using Gemini multimodal."""
    sample_pdf_bytes = b"%PDF-1.4 Mock PDF content for TCS offer"

    gemini_doc_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "ocr_text": "Tata Consultancy Services Offer Letter. Candidate selected for Software Engineer.",
                                "entities": {
                                    "company": "Tata Consultancy Services",
                                    "recruiter_name": "Priya Sen",
                                    "recruiter_email": "priya.sen@tcs.com",
                                    "job_role": "Software Engineer",
                                    "salary": "₹7 LPA",
                                    "salary_amount": 7.0,
                                    "salary_period": "LPA",
                                    "joining_date": "2026-09-01",
                                    "payment_request_detected": False,
                                    "payment_amount": None,
                                    "payment_method": None,
                                    "flags": [],
                                    "raw_text": "Tata Consultancy Services Offer Letter",
                                }
                            })
                        }
                    ]
                }
            }
        ]
    }

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = gemini_doc_response

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        result = await mock_gemini_client.extract_from_document(
            file_bytes=sample_pdf_bytes,
            mime_type="application/pdf"
        )

        assert "ocr_text" in result
        assert "entities" in result
        assert isinstance(result["entities"], ExtractedData)
        assert result["entities"].company == "Tata Consultancy Services"


@pytest.mark.asyncio
async def test_document_ocr_fallback_when_gemini_fails():
    """Test local fallback text extraction when file is uploaded without Gemini key."""
    extractor = EntityExtractor(gemini_client=GeminiClient(api_key=""))

    mock_pdf_bytes = b"%PDF-1.4 Infosys Offer Letter for Software Engineer. Package INR 6.5 LPA. hr@infosys.com"
    result = await extractor.extract_from_document(mock_pdf_bytes, "application/pdf")

    assert "ocr_text" in result
    assert "entities" in result
    assert isinstance(result["entities"], ExtractedData)
    assert result["entities"].company == "Infosys"
    assert result["entities"].recruiter_email == "hr@infosys.com"
