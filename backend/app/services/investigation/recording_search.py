"""
Recording and deduplicating search client wrapper for the investigation pipeline.

Preserves exact query provenance, latency, search metadata, and prevents duplicate searches.
Ensures provider failures are never converted into demo data unless demo_mode is True.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import time
from typing import Any, Dict, Generator, List, Optional

from app.schemas.contract import EventStatus, RetrievalStatus, ToolCall
from app.core.logging import logger


class RecordingSearchClient:
    """
    In-memory caching and provenance-recording search client wrapper.
    Wraps an underlying search client (e.g. SerpApiClient or MockSearchClient).
    """

    def __init__(self, underlying_client: Optional[Any] = None, demo_mode: bool = False):
        self._client = underlying_client
        self.demo_mode = demo_mode
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.tool_calls: List[ToolCall] = []
        self.snippets_by_url: Dict[str, List[Dict[str, Any]]] = {}
        self.failed_searches: List[Dict[str, Any]] = []

        self._current_step_name: Optional[str] = None
        self._current_step_reason: Optional[str] = None

    @contextmanager
    def step(self, name: str, reason: str) -> Generator[None, None, None]:
        prev_name = self._current_step_name
        prev_reason = self._current_step_reason
        self._current_step_name = name
        self._current_step_reason = reason
        try:
            yield
        finally:
            self._current_step_name = prev_name
            self._current_step_reason = prev_reason

    async def search(
        self,
        query: str,
        engine: str = "google",
        num: int = 5,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        normalized_key = f"{engine}:{query.strip().lower()}"
        if normalized_key in self._cache:
            logger.info("RecordingSearchClient: cache hit for query '%s'", query)
            return self._cache[normalized_key]

        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        tool_status = EventStatus.COMPLETED
        retrieval_status = RetrievalStatus.LIVE
        raw_res: Dict[str, Any] = {}

        try:
            if self._client is not None and hasattr(self._client, "search"):
                raw_res = await self._client.search(query=query, engine=engine, num=num, **kwargs)
            else:
                from app.services.search.serpapi_client import SerpApiClient
                fallback_client = SerpApiClient()
                raw_res = await fallback_client.search(query=query, engine=engine, num=num, **kwargs)
        except Exception as exc:
            duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
            err_msg = str(exc)
            raw_res = {
                "error": err_msg,
                "status": "error",
                "source": "FAILED",
                "organic_results": [],
            }
            self.failed_searches.append({
                "query": query,
                "engine": engine,
                "error": err_msg,
                "retrieved_at": started_at,
            })
            self.tool_calls.append(
                ToolCall(
                    step=self._current_step_name or "search",
                    tool=f"serpapi.{engine}",
                    query=query,
                    reason=self._current_step_reason or f"Search web via {engine}",
                    status=EventStatus.FAILED,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    evidence_ids=[],
                )
            )
            self._cache[normalized_key] = raw_res
            return raw_res

        duration_ms = max(0, int((time.perf_counter() - t0) * 1000))

        # Check raw response
        source = raw_res.get("source") if isinstance(raw_res, dict) else getattr(raw_res, "source", None)
        has_error = bool(raw_res.get("error") if isinstance(raw_res, dict) else getattr(raw_res, "error", None))
        status_field = raw_res.get("status") if isinstance(raw_res, dict) else getattr(raw_res, "status", None)

        if has_error or source == "FAILED" or status_field == "error":
            retrieval_status = RetrievalStatus.FAILED
            tool_status = EventStatus.FAILED
            err_msg = raw_res.get("error") if isinstance(raw_res, dict) else "Search provider failed"
            self.failed_searches.append({
                "query": query,
                "engine": engine,
                "error": err_msg or "Provider failure",
                "retrieved_at": started_at,
            })
        elif source == "DEMO":
            if self.demo_mode:
                retrieval_status = RetrievalStatus.DEMO
                tool_status = EventStatus.COMPLETED
            else:
                # In non-demo mode, synthetic/mock results from failures must not be promoted to live evidence
                retrieval_status = RetrievalStatus.FAILED
                tool_status = EventStatus.FAILED
                self.failed_searches.append({
                    "query": query,
                    "engine": engine,
                    "error": "Synthetic demo result rejected in production mode",
                    "retrieved_at": started_at,
                })
        else:
            retrieval_status = RetrievalStatus.LIVE
            tool_status = EventStatus.COMPLETED

        search_id = None
        if isinstance(raw_res, dict):
            search_id = raw_res.get("search_metadata", {}).get("id") or raw_res.get("search_id")
            organic = raw_res.get("organic_results") or []
            for item in organic:
                link = item.get("link")
                if link:
                    entry = {
                        "query": query,
                        "engine": engine,
                        "search_id": search_id,
                        "retrieved_at": started_at,
                        "retrieval_status": retrieval_status,
                        "title": item.get("title") or "",
                        "snippet": item.get("snippet") or "",
                        "source_url": link,
                    }
                    self.snippets_by_url.setdefault(link, []).append(entry)

        self.tool_calls.append(
            ToolCall(
                step=self._current_step_name or "search",
                tool=f"serpapi.{engine}",
                query=query,
                reason=self._current_step_reason or f"Search web via {engine}",
                status=tool_status,
                started_at=started_at,
                duration_ms=duration_ms,
                evidence_ids=[],
            )
        )

        self._cache[normalized_key] = raw_res
        return raw_res
