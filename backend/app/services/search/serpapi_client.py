import asyncio
import json
import re
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from enum import Enum
from typing import Dict, Any, List, Optional
import httpx

from app.core.config import settings
from app.core.logging import logger


class SearchOutcome(str, Enum):
    SUCCESS = "SUCCESS"  # Successful search with usable results
    ZERO_RESULTS = "ZERO_RESULTS"  # Successful search with zero results
    TIMEOUT = "TIMEOUT"  # Request timed out
    RATE_LIMIT = "RATE_LIMIT"  # Rate limit exceeded (HTTP 429)
    AUTH_FAILURE = "AUTH_FAILURE"  # Authentication or configuration failure
    PROVIDER_FAILURE = "PROVIDER_FAILURE"  # Upstream provider server error (5xx, connection drop, etc.)
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"  # Invalid or malformed provider response


class SearchSource(str, Enum):
    REAL = "REAL"
    MOCK = "MOCK"
    DEMO = "DEMO"
    FAILED = "FAILED"


def sanitize_search_text(text: str, api_key: Optional[str] = None) -> str:
    """Sanitizes text by stripping API keys and sensitive query parameters."""
    if not text:
        return ""
    sanitized = text
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    sanitized = re.sub(r"api_key=[^&\s'\"]+", "api_key=[REDACTED]", sanitized)
    sanitized = re.sub(r"https?://[^\s]+", "[REDACTED_URL]", sanitized)
    sanitized = re.sub(r"[\w.+-]+@[\w.-]+", "[REDACTED_EMAIL]", sanitized)
    sanitized = re.sub(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)", "[REDACTED_PHONE]", sanitized)
    return sanitized


class SearchResult(dict):
    """
    Consistent internal representation of search outcomes across AsliOffer.
    Inherits from dict to ensure 100% backward compatibility with all dictionary
    access patterns (`res.get("organic_results")`, `res["source"]`, `res.get("knowledge_graph")`)
    while exposing explicit structured properties for consumers.
    """

    def __init__(
        self,
        query: str,
        provider: str = "serpapi",
        outcome: SearchOutcome = SearchOutcome.SUCCESS,
        results: Optional[List[Dict[str, Any]]] = None,
        knowledge_graph: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        error_type: Optional[str] = None,
        status_code: Optional[int] = None,
        source: Optional[str] = None,
        search_metadata: Optional[Dict[str, Any]] = None,
        raw_response: Optional[Dict[str, Any]] = None,
    ):
        organic = results if results is not None else []
        kg = knowledge_graph if knowledge_graph is not None else {}
        is_success = outcome in (SearchOutcome.SUCCESS, SearchOutcome.ZERO_RESULTS)
        status_str = "successful" if is_success else "failed"

        if source is None:
            if is_success:
                source = SearchSource.REAL.value
            else:
                source = SearchSource.FAILED.value

        data: Dict[str, Any] = {
            "query": query,
            "provider": provider,
            "outcome": outcome.value if isinstance(outcome, SearchOutcome) else str(outcome),
            "status": status_str,
            "source": source,
            "organic_results": organic,
            "results": organic,
            "knowledge_graph": kg,
            "error": error,
            "error_type": error_type,
            "status_code": status_code,
        }
        if search_metadata:
            data["search_metadata"] = search_metadata
        if raw_response:
            data["raw_response"] = raw_response

        super().__init__(data)

    @property
    def query(self) -> str:
        return self["query"]

    @property
    def provider(self) -> str:
        return self["provider"]

    @property
    def outcome(self) -> SearchOutcome:
        return SearchOutcome(self["outcome"])

    @property
    def results(self) -> List[Dict[str, Any]]:
        return self["organic_results"]

    @property
    def organic_results(self) -> List[Dict[str, Any]]:
        return self["organic_results"]

    @property
    def knowledge_graph(self) -> Dict[str, Any]:
        return self["knowledge_graph"]

    @property
    def error(self) -> Optional[str]:
        return self["error"]

    @property
    def error_type(self) -> Optional[str]:
        return self.get("error_type")

    @property
    def status_code(self) -> Optional[int]:
        return self.get("status_code")

    @property
    def is_success(self) -> bool:
        return self.outcome == SearchOutcome.SUCCESS

    @property
    def is_empty(self) -> bool:
        return self.outcome == SearchOutcome.ZERO_RESULTS

    @property
    def is_available(self) -> bool:
        """True if search completed and gave usable or empty results (not failed/timed out/rate limited)."""
        return self.outcome in (SearchOutcome.SUCCESS, SearchOutcome.ZERO_RESULTS)

    @property
    def is_live(self) -> bool:
        """Only real completed searches may be used as external evidence."""
        return self.is_available and self.get("source") == SearchSource.REAL.value

    @classmethod
    def from_dict_or_result(cls, res: Any, query: str = "", provider: str = "serpapi") -> "SearchResult":
        """
        Adapts a legacy dictionary or mock fixture response into a canonical SearchResult.
        Guarantees that downstream callers always receive a structured SearchResult.
        """
        if not isinstance(res, dict):
            return cls(
                query=query,
                provider=provider,
                outcome=SearchOutcome.MALFORMED_RESPONSE,
                error="Response is not a valid dictionary or SearchResult",
                error_type="MalformedResponseError",
            )

        shape_error = validate_search_fields(res)
        if (not shape_error and not any(key in res for key in
                ("organic_results", "results", "knowledge_graph", "outcome", "error"))
                and res.get("status") != "failed"):
            shape_error = "Missing search result shape"
        if shape_error:
            return cls(query=query, provider=provider,
                       outcome=SearchOutcome.MALFORMED_RESPONSE,
                       error=shape_error, error_type="MalformedResponseError")

        # Explicit outcome field present
        if "outcome" in res:
            try:
                outcome = SearchOutcome(res["outcome"])
            except (ValueError, TypeError):
                return cls(query=query, provider=provider,
                           outcome=SearchOutcome.MALFORMED_RESPONSE,
                           error="Invalid search outcome", error_type="MalformedResponseError")
            return cls(
                query=res.get("query", query),
                provider=res.get("provider", provider),
                outcome=outcome,
                results=res.get("organic_results") if res.get("organic_results") is not None else res.get("results"),
                knowledge_graph=res.get("knowledge_graph"),
                error=sanitize_search_text(str(res.get("error") or "")) or None,
                error_type=res.get("error_type"),
                status_code=res.get("status_code"),
                source=res.get("source"),
                search_metadata=res.get("search_metadata"),
            )

        # Infer outcome from legacy fixture / mock response dict
        status = res.get("status")
        source = res.get("source")
        error = res.get("error")
        error_type = res.get("error_type")
        status_code = res.get("status_code")
        organic = res.get("organic_results") if res.get("organic_results") is not None else res.get("results")
        kg = res.get("knowledge_graph")

        if status == "failed" or source == SearchSource.FAILED.value or error:
            err_str = str(error or "").lower()
            err_t_str = str(error_type or "").lower()
            if status_code == 429 or "rate limit" in err_str or "ratelimit" in err_t_str:
                outcome = SearchOutcome.RATE_LIMIT
            elif status_code in (401, 403) or "invalid api key" in err_str or "authentication" in err_t_str or "unauthorized" in err_str:
                outcome = SearchOutcome.AUTH_FAILURE
            elif status_code == 408 or "timeout" in err_str or "timeout" in err_t_str:
                outcome = SearchOutcome.TIMEOUT
            elif "malformed" in err_str or "malformed" in err_t_str:
                outcome = SearchOutcome.MALFORMED_RESPONSE
            else:
                outcome = SearchOutcome.PROVIDER_FAILURE

            return cls(
                query=query,
                provider=provider,
                outcome=outcome,
                results=[],
                knowledge_graph=kg or {},
                error=sanitize_search_text(str(error or "Search request failed")),
                error_type=error_type or outcome.value,
                status_code=status_code,
                source=source or SearchSource.FAILED.value,
            )

        # Successful response: check if results exist
        has_results = bool(organic) or bool(kg and any(kg.values()))
        outcome = SearchOutcome.SUCCESS if has_results else SearchOutcome.ZERO_RESULTS
        return cls(
            query=query,
            provider=provider,
            outcome=outcome,
            results=organic or [],
            knowledge_graph=kg or {},
            source=source or SearchSource.REAL.value,
            search_metadata=res.get("search_metadata"),
        )


def validate_search_fields(data: Dict[str, Any]) -> Optional[str]:
    """Validate only fields agents consume; never echo provider values in errors."""
    organic = data.get("organic_results") if data.get("organic_results") is not None else data.get("results")
    if organic is not None:
        if not isinstance(organic, list):
            return "Expected organic_results to be a list"
        for item in organic:
            if not isinstance(item, dict):
                return "Expected each organic result to be an object"
            for key in ("link", "title", "snippet"):
                if key in item and not isinstance(item[key], str):
                    return "Invalid organic result text field"
            link = item.get("link")
            if not link or not item.get("title") or not _web_url(link):
                return "Organic result requires a title and HTTP(S) link"
    kg = data.get("knowledge_graph")
    if kg is not None:
        if not isinstance(kg, dict):
            return "Expected knowledge_graph to be an object"
        for key in ("website", "careers_url", "title"):
            if key in kg and not isinstance(kg[key], str):
                return "Invalid knowledge graph text field"
        for key in ("website", "careers_url"):
            if kg.get(key) and not _web_url(kg[key]):
                return "Invalid knowledge graph HTTP(S) link"
    for key in ("search_metadata", "search_information"):
        if key in data and not isinstance(data[key], dict):
            return "Invalid search metadata object"
        info = data.get(key) or {}
        for field in ("status", "organic_results_state"):
            if field in info and not isinstance(info[field], str):
                return "Invalid search metadata text field"
        if "total_results" in info and (isinstance(info["total_results"], bool)
                or not isinstance(info["total_results"], (int, float))):
            return "Invalid search result count"
    return None


def _web_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


def _retry_after(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            delay = max(0.0, (date - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None
    return delay if math.isfinite(delay) and delay >= 0 else None


class SerpApiClient:
    """
    Client interface for SerpApi to fetch live public search data across:
    - Google Search (official company presence, warnings, scam reports)
    - Google Jobs (active listings matching offer)
    - Google Knowledge Graph (official domain, registered office)

    Includes bounded failure handling, transient retry with backoff,
    explicit outcome representation, and zero fabricated fallbacks in production.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        retry_backoff: Optional[float] = None,
        demo_mode: Optional[bool] = None,
        total_timeout: Optional[float] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.SERPAPI_API_KEY
        self.base_url = "https://serpapi.com/search.json"
        self.timeout = timeout if timeout is not None else settings.SEARCH_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.SEARCH_MAX_RETRIES
        self.retry_backoff = retry_backoff if retry_backoff is not None else settings.SEARCH_RETRY_BACKOFF_SECONDS
        self.demo_mode = demo_mode if demo_mode is not None else settings.SEARCH_DEMO_MODE
        self.total_timeout = total_timeout if total_timeout is not None else settings.SEARCH_TOTAL_TIMEOUT_SECONDS
        for name, value in (("timeout", self.timeout), ("total_timeout", self.total_timeout)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not isinstance(self.max_retries, int) or not 0 <= self.max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5")
        if not math.isfinite(self.retry_backoff) or not 0 <= self.retry_backoff <= 5:
            raise ValueError("retry_backoff must be between 0 and 5")

    async def search(
        self, query: str, engine: str = "google", num: int = 5,
        fallback_to_mock: bool = False,
    ) -> SearchResult:
        """Bound the complete operation, including HTTP work and retry sleeps.

        fallback_to_mock is retained for caller compatibility and never enables
        synthetic evidence. Demo results require explicit SEARCH_DEMO_MODE.
        """
        logger.info("SerpApiClient search started (engine=%s)", engine)
        if self.demo_mode:
            return self._demo_search_results(query)
        if not self.api_key or not self.api_key.strip() or self.api_key == "mock_key":
            return self._failure(query, SearchOutcome.AUTH_FAILURE,
                                 "Search credentials are missing or invalid", 401)
        try:
            async with asyncio.timeout(self.total_timeout):
                return await self._search_live(query, engine, num)
        except TimeoutError:
            return self._failure(query, SearchOutcome.TIMEOUT,
                                 "Search exceeded its overall time budget")
        except Exception:
            # Client/proxy setup failures occur before the request retry loop.
            # Cancellation is a BaseException and continues to propagate.
            return self._failure(query, SearchOutcome.PROVIDER_FAILURE,
                                 "Search client could not complete the operation")

    @staticmethod
    def _failure(query: str, outcome: SearchOutcome, message: str,
                 status_code: Optional[int] = None) -> SearchResult:
        # Use fixed messages rather than provider payloads or request URLs.
        logger.warning("SerpApiClient search unavailable (outcome=%s)", outcome.value)
        return SearchResult(query=query, outcome=outcome, error=message,
                            error_type=outcome.value, status_code=status_code)

    async def _search_live(self, query: str, engine: str, num: int) -> SearchResult:
        params = {"q": query, "engine": engine, "num": num, "api_key": self.api_key}
        for key, value in (("gl", settings.SEARCH_COUNTRY), ("hl", settings.SEARCH_LANGUAGE),
                           ("google_domain", settings.SEARCH_GOOGLE_DOMAIN)):
            if value:
                params[key] = value
        max_attempts = self.max_retries + 1
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(max_attempts):
                delay = self.retry_backoff * (2 ** attempt)
                retryable = False
                try:
                    response = await client.get(self.base_url, params=params)
                    code = response.status_code
                    if code in (401, 403):
                        return self._failure(query, SearchOutcome.AUTH_FAILURE,
                                             "Search authentication failed", code)
                    if code == 429:
                        result = self._failure(query, SearchOutcome.RATE_LIMIT,
                                               "Search rate limit exceeded", code)
                        retry_delay = _retry_after(response.headers.get("Retry-After"))
                        if retry_delay is not None:
                            delay = retry_delay
                        # Long waits are returned to the caller; never retry early.
                        retryable = delay <= 2.0
                    elif code >= 500:
                        result = self._failure(query, SearchOutcome.PROVIDER_FAILURE,
                                               "Search provider server error", code)
                        retryable = code in (500, 502, 503, 504)
                    elif code >= 400:
                        return self._failure(query, SearchOutcome.PROVIDER_FAILURE,
                                             "Search request rejected", code)
                    elif not 200 <= code < 300:
                        return self._failure(query, SearchOutcome.PROVIDER_FAILURE,
                                             "Unexpected search HTTP status", code)
                    else:
                        try:
                            data = response.json()
                        except (ValueError, json.JSONDecodeError):
                            return self._failure(query, SearchOutcome.MALFORMED_RESPONSE,
                                                 "Malformed JSON response", code)
                        if not isinstance(data, dict):
                            return self._failure(query, SearchOutcome.MALFORMED_RESPONSE,
                                                 "Expected a JSON object", code)
                        shape_error = validate_search_fields(data)
                        if shape_error:
                            return self._failure(query, SearchOutcome.MALFORMED_RESPONSE,
                                                 shape_error, code)
                        if "error" in data:
                            if not isinstance(data["error"], str):
                                return self._failure(query, SearchOutcome.MALFORMED_RESPONSE,
                                                     "Invalid provider error field", code)
                            error = data["error"].lower()
                            if "hasn't returned any results" in error or "no results found" in error:
                                return SearchResult(query=query, outcome=SearchOutcome.ZERO_RESULTS)
                            if any(term in error for term in ("api key", "invalid api", "unauthorized", "api_key")):
                                return self._failure(query, SearchOutcome.AUTH_FAILURE,
                                                     "Search authentication failed", code)
                            if any(term in error for term in ("rate limit", "exceeded", "out of searches")):
                                return self._failure(query, SearchOutcome.RATE_LIMIT,
                                                     "Search quota or rate limit exceeded", code)
                            result = self._failure(query, SearchOutcome.PROVIDER_FAILURE,
                                                   "Search provider reported an error", code)
                            retryable = any(term in error for term in (
                                "temporarily unavailable", "temporary error", "internal server error", "try again"))
                        else:
                            metadata = data.get("search_metadata") or {}
                            information = data.get("search_information") or {}
                            status = metadata.get("status")
                            if status and status != "Success":
                                result = self._failure(query, SearchOutcome.PROVIDER_FAILURE,
                                                       "Search provider did not complete the search", code)
                                retryable = status in ("Queued", "Processing")
                            else:
                                organic = data.get("organic_results")
                                kg = data.get("knowledge_graph")
                                explicitly_empty = any(
                                    info.get("total_results") == 0 or info.get("organic_results_state") == "Fully empty"
                                    for info in (metadata, information))
                                if organic is None and kg is None and not explicitly_empty:
                                    return self._failure(query, SearchOutcome.MALFORMED_RESPONSE,
                                                         "Missing search results and empty-result indication", code)
                                has_results = bool(organic) or bool(kg and any(kg.values()))
                                # Do not retain raw provider request URLs/parameters.
                                safe_metadata = {"status": status} if status else None
                                return SearchResult(
                                    query=query, outcome=SearchOutcome.SUCCESS if has_results else SearchOutcome.ZERO_RESULTS,
                                    results=organic or [], knowledge_graph=kg or {}, search_metadata=safe_metadata)
                except httpx.TimeoutException:
                    result = self._failure(query, SearchOutcome.TIMEOUT, "Search request timed out")
                    retryable = True
                except (httpx.NetworkError, httpx.RemoteProtocolError):
                    result = self._failure(query, SearchOutcome.PROVIDER_FAILURE,
                                           "Connection error reaching search provider")
                    retryable = True
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return self._failure(query, SearchOutcome.PROVIDER_FAILURE,
                                         "Unexpected search integration failure")
                if not retryable or attempt + 1 == max_attempts:
                    return result
                await asyncio.sleep(delay)
        return self._failure(query, SearchOutcome.PROVIDER_FAILURE, "Search attempts exhausted")

    def _demo_search_results(self, query: str) -> SearchResult:
        """
        Isolated demo fixture responses for offline development or explicit demo mode.
        Clearly tagged as source=DEMO and never used in production verification.
        """
        q = query.lower()

        if "scam" in q or "fraud" in q or "fake" in q or "fee" in q:
            return SearchResult(
                query=query,
                provider="serpapi",
                outcome=SearchOutcome.SUCCESS,
                source=SearchSource.DEMO.value,
                results=[
                    {
                        "title": "Advisory: Reported Job Recruitment Scams",
                        "link": "https://cybercrime.gov.in/Webform/Crime_Autho_List.aspx",
                        "snippet": "Beware of unsolicited recruitment requesting upfront registration or training deposits.",
                    },
                ],
            )

        return SearchResult(
            query=query,
            provider="serpapi",
            outcome=SearchOutcome.ZERO_RESULTS,
            source=SearchSource.DEMO.value,
            results=[],
            knowledge_graph={},
        )
