"""Per-run search recording with task-local context and exact-query deduplication."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import time
from typing import Any, Dict, List, Optional

from app.schemas.contract import EventStatus, RetrievalStatus, ToolCall
from app.services.search.serpapi_client import SearchResult, SearchOutcome, SearchSource
from app.services.agents.scam_classifier import sanitize_and_redact_secrets
from app.services.investigation.events import sanitize_public_message
from app.services.investigation.budget import BudgetManager, InvestigationBudget


class RecordingSearchClient:
    def __init__(
        self,
        underlying_client: Optional[Any] = None,
        demo_mode: bool = False,
        budget_manager: Optional[BudgetManager] = None,
    ):
        self._client = underlying_client
        self.demo_mode = demo_mode
        self.budget_manager = budget_manager or BudgetManager()
        self._cache = {}
        self._locks = {}
        self._context = ContextVar(f'search_context_{id(self)}', default=('search', 'Search public records'))
        self.tool_calls: List[ToolCall] = []
        self.snippets_by_url: Dict[str, List[Dict[str, Any]]] = {}
        self.failed_searches: List[Dict[str, Any]] = []

    @contextmanager
    def step(self, name, reason):
        token = self._context.set((name, reason))
        try:
            yield
        finally:
            self._context.reset(token)

    async def search(self, query: str, engine: str = 'google', num: int = 5, **kwargs):
        # Only semantically identical requests share a response. Case-sensitive
        # quoted queries and result-count/options remain distinct.
        query = sanitize_public_message(sanitize_and_redact_secrets(query)).strip()
        key = json.dumps([engine, query, num, kwargs], sort_keys=True, default=str)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # 1. Exact cache lookup (cache hits consume zero search budget)
            if key in self._cache:
                return deepcopy(self._cache[key])

            step, reason = self._context.get()
            started_at = datetime.now(timezone.utc)
            t0 = time.perf_counter()

            # 2. Check for missing or redacted placeholder inputs (never search placeholders)
            if re.search(r'\[(?:email|phone|redacted|candidate|company|employer|upi)[^\]]*\]|unknown (?:company|employer)|^\"\"', query, re.I):
                return SearchResult(query=query, outcome=SearchOutcome.PROVIDER_FAILURE,
                                    error='Required search input is missing or redacted')

            # 3. Admission check against shared budget & monotonic deadline
            is_followup = step.startswith("adaptive_")
            admitted, denial_reason, denial_type = await self.budget_manager.try_admit(
                is_followup=is_followup, query=query, step=step
            )
            if not admitted:
                # Budget/deadline denial must make no provider call and not be permanently cached
                outcome = (
                    SearchOutcome.AUTH_FAILURE if denial_type == "AUTH_FAILURE"
                    else SearchOutcome.TIMEOUT if denial_type == "DEADLINE_EXCEEDED"
                    else SearchOutcome.RATE_LIMIT
                )
                res = SearchResult(
                    query=query,
                    outcome=outcome,
                    error=denial_reason or "Search call denied by investigation budget",
                    source=SearchSource.FAILED.value,
                )
                res["budget_denied"] = True
                res["denial_type"] = denial_type
                # No fabricated successful tool call is created
                return res

            # 4. Admitted call executed under concurrency semaphore and remaining deadline
            try:
                if self._client is None:
                    from app.services.search.serpapi_client import SerpApiClient
                    self._client = SerpApiClient()

                async with self.budget_manager.semaphore:
                    remaining = self.budget_manager.remaining_seconds
                    if remaining <= 0:
                        raw = SearchResult(query=query, outcome=SearchOutcome.TIMEOUT,
                                           error='Investigation elapsed deadline expired during concurrency wait')
                    else:
                        raw = await asyncio.wait_for(
                            self._client.search(query=query, engine=engine, num=num, **kwargs),
                            timeout=remaining,
                        )
                result = SearchResult.from_dict_or_result(raw, query=query)
            except asyncio.TimeoutError:
                result = SearchResult(query=query, outcome=SearchOutcome.TIMEOUT,
                                      error='Investigation elapsed deadline expired')
            except asyncio.CancelledError:
                self.tool_calls.append(ToolCall(step=step, tool=f'serpapi.{engine}', query=query,
                    reason=reason, status=EventStatus.FAILED, started_at=started_at,
                    duration_ms=max(0, int((time.perf_counter()-t0)*1000))))
                raise
            except Exception:
                result = SearchResult(query=query, outcome=SearchOutcome.PROVIDER_FAILURE,
                                      error='Search request failed')

            # Detect auth failure to suppress futile follow-ups
            if result.outcome == SearchOutcome.AUTH_FAILURE or result.get("error_type") == "AUTH_FAILURE":
                self.budget_manager.record_auth_failure()

            source = result.get('source')
            synthetic = source in ('DEMO', 'MOCK')
            failed = not result.is_available or (synthetic and not self.demo_mode)
            if failed:
                result = SearchResult(query=query, outcome=result.outcome if not result.is_available else SearchOutcome.PROVIDER_FAILURE,
                                      error=result.error or 'Search result unavailable', source='FAILED')
                self.failed_searches.append({'query': query, 'engine': engine, 'error': result.error or 'Search result unavailable',
                                            'retrieved_at': started_at, 'step': step})
            status = RetrievalStatus.FAILED if failed else RetrievalStatus.DEMO if synthetic else RetrievalStatus.LIVE
            call = ToolCall(step=step, tool=f'serpapi.{engine}', query=query, reason=reason,
                           status=EventStatus.FAILED if failed else EventStatus.COMPLETED,
                           started_at=started_at, duration_ms=max(0, int((time.perf_counter()-t0)*1000)))
            self.tool_calls.append(call)
            if not failed:
                metadata = result.get('search_metadata') or {}
                search_id = metadata.get('id') or result.get('search_id')
                items = list(result.organic_results)
                # Knowledge graph URLs are real retrieved observations too, not
                # invented organic-result snippets.
                kg = result.get('knowledge_graph') or {}
                for field in ('website', 'careers_url'):
                    if isinstance(kg.get(field), str):
                        items.append({'link': kg[field], 'title': kg.get('title', ''),
                                      'snippet': json.dumps(kg, ensure_ascii=False)})
                for item in items:
                    if not isinstance(item, dict) or not item.get('link'):
                        continue
                    self.snippets_by_url.setdefault(item['link'], []).append({
                        'query': query, 'engine': engine, 'search_id': search_id,
                        'retrieved_at': started_at, 'retrieval_status': status,
                        'title': item.get('title') or '', 'snippet': item.get('snippet') or '',
                        'source_url': item['link'], 'step': step, 'call': call})
            self._cache[key] = deepcopy(result)
            return deepcopy(result)
