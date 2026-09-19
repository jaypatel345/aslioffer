from typing import Dict, Any, List, Optional
import httpx
from app.core.config import settings
from app.core.logging import logger


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

    async def search(self, query: str, engine: str = "google", num: int = 5) -> Dict[str, Any]:
        """
        Execute a search query. Falls back to deterministic mock if no API key is configured.
        """
        logger.info("SerpApiClient query: '%s' (engine=%s)", query, engine)

        if not self.api_key or self.api_key == "mock_key":
            return self._mock_search_results(query)

        params = {
            "q": query,
            "engine": engine,
            "num": num,
            "api_key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.warning("Live SerpApi request failed (%s). Falling back to mock data.", str(e))
            return self._mock_search_results(query)

    def _mock_search_results(self, query: str) -> Dict[str, Any]:
        """Returns structured mock public footprint data."""
        q = query.lower()

        # Scam warning scenario
        if "scam" in q or "fraud" in q or "fake" in q or "fee" in q:
            return {
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
                ]
            }

        # Company knowledge scenario
        return {
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
