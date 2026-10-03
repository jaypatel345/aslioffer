import json
from pathlib import Path
from typing import Dict, Any, List
import pytest
from app.services.search.serpapi_client import SerpApiClient

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "investigation"


def load_all_fixtures() -> List[Dict[str, Any]]:
    """Loads all 16 JSON investigation fixtures from the fixture directory."""
    fixtures = []
    for json_file in sorted(FIXTURES_DIR.glob("case_*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            fixtures.append(data)
    return fixtures


def load_fixture_by_id(case_id: str) -> Dict[str, Any]:
    """Loads a specific investigation fixture by case_id."""
    for fixture in load_all_fixtures():
        if fixture.get("case_id") == case_id:
            return fixture
    raise FileNotFoundError(f"Fixture with case_id '{case_id}' not found in {FIXTURES_DIR}")


class MockSearchClient(SerpApiClient):
    """
    Injected deterministic search client that replays search responses
    from fixture query_responses mappings without making any network calls.
    """

    def __init__(self, query_responses: Dict[str, Any], default_response: Dict[str, Any] = None):
        super().__init__(api_key="mock-key-investigation")
        self.query_responses = query_responses or {}
        self.default_response = default_response or {"status": "successful", "source": "mock", "organic_results": []}
        self.recorded_queries: List[str] = []

    async def search(self, query: str, engine: str = "google", num: int = 5) -> Dict[str, Any]:
        self.recorded_queries.append(query)
        # Check exact query
        if query in self.query_responses:
            return self.query_responses[query]

        # Check partial or normalized match
        query_clean = query.strip()
        for q_key, resp in self.query_responses.items():
            if q_key.strip() == query_clean:
                return resp

        return self.default_response


@pytest.fixture
def all_investigation_fixtures():
    return load_all_fixtures()
