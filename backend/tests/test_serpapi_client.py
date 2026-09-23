import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from app.services.search.serpapi_client import SerpApiClient, SearchSource


@pytest.mark.asyncio
async def test_live_success():
    """Verify successful live SerpApi call sets source to REAL and preserves payload."""
    client = SerpApiClient(api_key="valid_live_key")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "organic_results": [
            {"title": "Tata Consultancy Services", "link": "https://www.tcs.com", "snippet": "Official site"}
        ],
        "knowledge_graph": {"website": "https://www.tcs.com"},
    }
    mock_response.raise_for_status.return_value = None

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        res = await client.search("TCS official careers")

        assert res["source"] == SearchSource.REAL.value
        assert "organic_results" in res
        assert res["organic_results"][0]["title"] == "Tata Consultancy Services"
        assert res["knowledge_graph"]["website"] == "https://www.tcs.com"
        mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_timeout_fallback():
    """Verify request timeout activates mock fallback with source MOCK."""
    client = SerpApiClient(api_key="valid_live_key")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ReadTimeout("Read timed out after 10.0s")

        res = await client.search("Wipro official careers")

        assert res["source"] == SearchSource.MOCK.value
        assert "organic_results" in res
        assert len(res["organic_results"]) > 0
        assert "knowledge_graph" in res


@pytest.mark.asyncio
async def test_rate_limit_fallback():
    """Verify HTTP 429 rate limit triggers mock fallback with source MOCK."""
    client = SerpApiClient(api_key="valid_live_key")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.text = "Too Many Requests"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        # Scam query should hit scam mock branch
        res = await client.search("TechCorp scam fake fee")

        assert res["source"] == SearchSource.MOCK.value
        assert "organic_results" in res
        assert any("scam" in r["title"].lower() or "warning" in r["title"].lower() for r in res["organic_results"])


@pytest.mark.asyncio
async def test_invalid_key_fallback_local():
    """Verify unconfigured or 'mock_key' immediately triggers mock fallback without network call."""
    # Empty key
    client_empty = SerpApiClient(api_key="")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        res = await client_empty.search("Google careers")
        assert res["source"] == SearchSource.MOCK.value
        mock_get.assert_not_called()

    # Mock key string
    client_mock = SerpApiClient(api_key="mock_key")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        res = await client_mock.search("Google careers")
        assert res["source"] == SearchSource.MOCK.value
        mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_key_fallback_remote():
    """Verify HTTP 401/403 or error in JSON response triggers mock fallback."""
    client = SerpApiClient(api_key="bad_token")

    # Case A: 401 Status Code
    mock_401 = MagicMock(spec=httpx.Response)
    mock_401.status_code = 401

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_401
        res = await client.search("Accenture careers")
        assert res["source"] == SearchSource.MOCK.value

    # Case B: JSON error payload with status 200
    mock_json_err = MagicMock(spec=httpx.Response)
    mock_json_err.status_code = 200
    mock_json_err.raise_for_status.return_value = None
    mock_json_err.json.return_value = {"error": "Invalid API key."}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_json_err
        res = await client.search("Accenture careers")
        assert res["source"] == SearchSource.MOCK.value


@pytest.mark.asyncio
async def test_fallback_disabled_returns_failed():
    """Verify that when fallback_to_mock=False, failures return source FAILED with error details."""
    client = SerpApiClient(api_key="valid_live_key")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectTimeout("Connection refused")

        res = await client.search("Company", fallback_to_mock=False)
        assert res["source"] == SearchSource.FAILED.value
        assert "error" in res
        assert "organic_results" in res


@pytest.mark.asyncio
async def test_consumer_backwards_compatibility():
    """Ensure CompanyAgent and RecruiterAgent property access patterns remain 100% compatible."""
    client = SerpApiClient(api_key="")

    res = await client.search("Infosys official website careers")

    # Consumers access these keys directly
    knowledge_graph = res.get("knowledge_graph") or {}
    organic_results = res.get("organic_results") or []
    source = res.get("source")

    assert source in (SearchSource.REAL.value, SearchSource.MOCK.value)
    assert isinstance(knowledge_graph, dict)
    assert isinstance(organic_results, list)
    assert "website" in knowledge_graph
    assert len(organic_results) > 0
