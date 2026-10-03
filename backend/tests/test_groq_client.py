"""Groq vision client: contract and failure handling, no network required."""
import base64
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.schemas.analysis import ExtractedData
from app.services.ai.groq_client import (
    GroqClient,
    GroqError,
    GroqParseError,
    GroqRateLimitError,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _response(status=200, payload=None):
    return httpx.Response(
        status_code=status,
        json=payload if payload is not None else {},
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )


def _ok_body(ocr="Offer from Coorix", entities=None):
    content = json.dumps({
        "ocr_text": ocr,
        "entities": entities if entities is not None else {"company": "Coorix", "flags": []},
    })
    return {"choices": [{"message": {"content": content}}]}


@pytest.mark.asyncio
async def test_missing_key_raises():
    with pytest.raises(GroqError, match="not configured"):
        await GroqClient(api_key="").extract_from_document(PNG, "image/png")


@pytest.mark.asyncio
async def test_pdf_is_rejected_so_gemini_can_try():
    """Groq vision takes raster images only; PDFs must fall through, not fail hard."""
    with pytest.raises(ValueError, match="does not accept"):
        await GroqClient(api_key="k").extract_from_document(PNG, "application/pdf")


@pytest.mark.asyncio
async def test_oversized_image_rejected():
    client = GroqClient(api_key="k")
    with pytest.raises(ValueError, match="at most 20MB"):
        await client.extract_from_document(b"x" * (client.MAX_IMAGE_BYTES + 1), "image/png")


@pytest.mark.asyncio
async def test_successful_extraction_returns_gemini_shape():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _response(200, _ok_body())
        result = await GroqClient(api_key="k").extract_from_document(PNG, "image/png")

    assert set(result) == {"ocr_text", "entities"}
    assert result["ocr_text"] == "Offer from Coorix"
    assert isinstance(result["entities"], ExtractedData)
    assert result["entities"].company == "Coorix"
    # raw_text is backfilled from the transcription when the model omits it
    assert result["entities"].raw_text == "Offer from Coorix"


@pytest.mark.asyncio
async def test_rate_limit_raises_after_retries():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _response(429, {"error": "rate limited"})
        with pytest.raises(GroqRateLimitError):
            await GroqClient(api_key="k").extract_from_document(PNG, "image/png")
        assert post.await_count == GroqClient.MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_markdown_fenced_json_is_parsed():
    body = {"choices": [{"message": {"content": '```json\n{"ocr_text":"hi","entities":{}}\n```'}}]}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _response(200, body)
        result = await GroqClient(api_key="k").extract_from_document(PNG, "image/png")
    assert result["ocr_text"] == "hi"


@pytest.mark.asyncio
async def test_non_json_output_raises_parse_error():
    body = {"choices": [{"message": {"content": "I cannot read this image."}}]}
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _response(200, body)
        with pytest.raises(GroqParseError):
            await GroqClient(api_key="k").extract_from_document(PNG, "image/png")


@pytest.mark.asyncio
async def test_extractor_prefers_groq_and_never_calls_gemini():
    from app.services.extractor.entity_extractor import EntityExtractor

    groq, gemini = GroqClient(api_key="k"), AsyncMock()
    gemini.api_key = "g"
    extractor = EntityExtractor(gemini_client=gemini, groq_client=groq)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _response(200, _ok_body())
        result = await extractor.extract_from_document(PNG, "image/png")

    assert result["entities"].company == "Coorix"
    gemini.extract_from_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_extractor_falls_back_to_gemini_when_groq_rate_limited():
    """The whole point of the chain: Groq 429 must not end the upload."""
    from app.services.extractor.entity_extractor import EntityExtractor

    groq, gemini = GroqClient(api_key="k"), AsyncMock()
    gemini.api_key = "g"
    gemini.extract_from_document.return_value = {
        "ocr_text": "via gemini",
        "entities": ExtractedData(company="Coorix"),
    }
    extractor = EntityExtractor(gemini_client=gemini, groq_client=groq)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        post.return_value = _response(429, {"error": "rate limited"})
        result = await extractor.extract_from_document(PNG, "image/png")

    assert result["ocr_text"] == "via gemini"
    gemini.extract_from_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_pdf_skips_groq_and_goes_straight_to_gemini():
    from app.services.extractor.entity_extractor import EntityExtractor

    groq, gemini = GroqClient(api_key="k"), AsyncMock()
    gemini.api_key = "g"
    gemini.extract_from_document.return_value = {
        "ocr_text": "pdf text",
        "entities": ExtractedData(company="Coorix"),
    }
    extractor = EntityExtractor(gemini_client=gemini, groq_client=groq)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        result = await extractor.extract_from_document(b"%PDF-1.4", "application/pdf")
        post.assert_not_awaited()

    assert result["ocr_text"] == "pdf text"
    gemini.extract_from_document.assert_awaited_once()
