from enum import Enum
from typing import Dict, Any, List, Optional
import httpx
from app.core.config import settings
from app.core.logging import logger


class SearchSource(str, Enum):
    REAL = "REAL"
    MOCK = "MOCK"
    FAILED = "FAILED"


class SerpApiClient:
    """
    Client interface for SerpApi to fetch live public search data across:
    - Google Search (official company presence, warnings, scam reports)
    - Google Jobs (active listings matching offer)
    - Google Knowledge Graph (official domain, registered office)
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.SERPAPI_API_KEY
        self.base_url = "https://serpapi.com/search.json"

    async def search(
        self,
        query: str,
        engine: str = "google",
        num: int = 5,
        fallback_to_mock: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a search query. Falls back to deterministic mock if no API key is configured
        or on live API failure when fallback_to_mock is True.
        """
        logger.info("SerpApiClient query: '%s' (engine=%s)", query, engine)

        if not self.api_key:
            logger.warning("SerpApiClient: invalid API key (missing or empty). Mock fallback activation.")
            if fallback_to_mock:
                return self._mock_search_results(query, source=SearchSource.MOCK)
            return {"source": SearchSource.FAILED.value, "error": "Invalid API key", "organic_results": []}

        if self.api_key == "mock_key":
            logger.info("SerpApiClient: mock key detected. Mock fallback activation.")
            if fallback_to_mock:
                return self._mock_search_results(query, source=SearchSource.MOCK)
            return {"source": SearchSource.FAILED.value, "error": "Mock key provided", "organic_results": []}

        params = {
            "q": query,
            "engine": engine,
            "num": num,
            "api_key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.base_url, params=params)

                if response.status_code == 429:
                    logger.warning("SerpApiClient: HTTP 429 rate limit reached for query '%s'. Mock fallback activation.", query)
                    if fallback_to_mock:
                        return self._mock_search_results(query, source=SearchSource.MOCK)
                    return {"source": SearchSource.FAILED.value, "error": "HTTP 429 rate limit exceeded", "organic_results": []}

                if response.status_code in (401, 403):
                    logger.warning(
                        "SerpApiClient: invalid API key (status %d) for query '%s'. Mock fallback activation.",
                        response.status_code,
                        query,
                    )
                    if fallback_to_mock:
                        return self._mock_search_results(query, source=SearchSource.MOCK)
                    return {"source": SearchSource.FAILED.value, "error": f"Invalid API key (status {response.status_code})", "organic_results": []}

                response.raise_for_status()
                data = response.json()

                if isinstance(data, dict) and "error" in data:
                    err_msg = str(data["error"])
                    if "api key" in err_msg.lower() or "invalid" in err_msg.lower():
                        logger.warning("SerpApiClient: invalid API key in response ('%s'). Mock fallback activation.", err_msg)
                    else:
                        logger.warning("SerpApiClient: API error returned ('%s'). Mock fallback activation.", err_msg)

                    if fallback_to_mock:
                        return self._mock_search_results(query, source=SearchSource.MOCK)
                    return {"source": SearchSource.FAILED.value, "error": err_msg, "organic_results": []}

                logger.info("SerpApiClient: API success for query '%s'", query)
                data["source"] = SearchSource.REAL.value
                return data

        except httpx.TimeoutException as e:
            logger.warning("SerpApiClient: API timeout after 10.0s for query '%s' (%s). Mock fallback activation.", query, str(e))
            if fallback_to_mock:
                return self._mock_search_results(query, source=SearchSource.MOCK)
            return {"source": SearchSource.FAILED.value, "error": f"API timeout: {str(e)}", "organic_results": []}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("SerpApiClient: HTTP 429 rate limit reached for query '%s'. Mock fallback activation.", query)
            elif e.response.status_code in (401, 403):
                logger.warning("SerpApiClient: invalid API key (status %d) for query '%s'. Mock fallback activation.", e.response.status_code, query)
            else:
                logger.warning("SerpApiClient: HTTP status error %d for query '%s'. Mock fallback activation.", e.response.status_code, query)

            if fallback_to_mock:
                return self._mock_search_results(query, source=SearchSource.MOCK)
            return {"source": SearchSource.FAILED.value, "error": str(e), "organic_results": []}

        except Exception as e:
            logger.warning("SerpApiClient: live request failed (%s) for query '%s'. Mock fallback activation.", str(e), query)
            if fallback_to_mock:
                return self._mock_search_results(query, source=SearchSource.MOCK)
            return {"source": SearchSource.FAILED.value, "error": str(e), "organic_results": []}

    def _mock_search_results(self, query: str, source: SearchSource = SearchSource.MOCK) -> Dict[str, Any]:
        """Returns structured mock public footprint data."""
        q = query.lower()

        # Scam warning scenario
        if "scam" in q or "fraud" in q or "fake" in q or "fee" in q:
            return {
                "source": source.value,
                "organic_results": [
                    {
                        "title": f"Warning: Fraudulent job offers misusing {query.split()[0]} name",
                        "link": "https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                        "snippet": "Beware of unsolicited messages on Telegram and WhatsApp claiming to offer high-paying roles with upfront laptop/training fees.",
                    },
                    {
                        "title": "Community Scam Registry: Reported Fake Recruiter Numbers",
                        "link": "https://scamadviser.com/check-website",
                        "snippet": "Multiple reports found for fraudulent recruitment using free public email domains (gmail, outlook).",
                    },
                ],
            }

        # Company knowledge scenario
        return {
            "source": source.value,
            "knowledge_graph": {
                "title": query,
                "website": f"https://www.{query.lower().replace(' ', '')}.com",
                "careers_url": f"https://careers.{query.lower().replace(' ', '')}.com",
            },
            "organic_results": [
                {
                    "title": f"Official Portal | {query}",
                    "link": f"https://www.{query.lower().replace(' ', '')}.com",
                    "snippet": f"Official home page of {query}. Verify registered offices and leadership.",
                },
                {
                    "title": f"Careers at {query} - Official Job Board",
                    "link": f"https://careers.{query.lower().replace(' ', '')}.com",
                    "snippet": "Explore official vacancies. We never ask candidates for security deposits or training fees.",
                },
            ],
        }
