import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any, List

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


class MockSearchClient:
    """
    Injected deterministic search client that replays search responses
    from fixture query_responses mappings without making any network calls.
    """

    def __init__(self, query_responses: Dict[str, Any], default_response: Dict[str, Any] = None):
        self.query_responses = query_responses or {}
        self.default_response = default_response or {"status": "successful", "source": "DEMO", "organic_results": []}
        self.recorded_queries: List[str] = []
        self.unmatched_queries: List[str] = []

    async def search(self, query: str, engine: str = "google", num: int = 5, fallback_to_mock: bool = True) -> Dict[str, Any]:
        self.recorded_queries.append(query)
        # Check exact query
        if query in self.query_responses:
            return self._replay(self.query_responses[query])

        # Check partial or normalized match
        query_clean = query.strip()
        for q_key, resp in self.query_responses.items():
            if q_key.strip() == query_clean:
                return self._replay(resp)

        self.unmatched_queries.append(query)
        return self._replay(self.default_response)

    @staticmethod
    def _replay(response):
        # Fixture DEMO labels describe synthetic corpus provenance. Replay them
        # as simulated live provider responses so agent/domain regressions are
        # exercised, rather than short-circuited by production demo isolation.
        replay = deepcopy(response)
        if replay.get("source") == "DEMO" and replay.get("status") == "successful":
            replay["source"] = "REAL"
        return replay
