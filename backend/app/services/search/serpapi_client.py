import asyncio
import json
import re
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
    if api_key and len(api_key) > 4:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    sanitized = re.sub(r"api_key=[^&\s'\"]+", "api_key=[REDACTED]", sanitized)
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

    @classmethod
    def from_dict_or_result(cls, res: Any, query: str = "", provider: str = "serpapi") -> "SearchResult":
        """
        Adapts a legacy dictionary or mock fixture response into a canonical SearchResult.
        Guarantees that downstream callers always receive a structured SearchResult.
        """
        if isinstance(res, cls):
            return res

        if not isinstance(res, dict):
            return cls(
                query=query,
                provider=provider,
                outcome=SearchOutcome.MALFORMED_RESPONSE,
                error="Response is not a valid dictionary or SearchResult",
                error_type="MalformedResponseError",
            )

        # Explicit outcome field present
        if "outcome" in res:
            try:
                outcome = SearchOutcome(res["outcome"])
            except ValueError:
                outcome = SearchOutcome.SUCCESS if res.get("status") == "successful" else SearchOutcome.PROVIDER_FAILURE
            return cls(
                query=res.get("query", query),
                provider=res.get("provider", provider),
                outcome=outcome,
                results=res.get("organic_results") if res.get("organic_results") is not None else res.get("results"),
                knowledge_graph=res.get("knowledge_graph"),
                error=res.get("error"),
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
                error=error or "Search request failed",
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
    ):
        self.api_key = api_key if api_key is not None else settings.SERPAPI_API_KEY
        self.base_url = "https://serpapi.com/search.json"
        self.timeout = timeout if timeout is not None else settings.SEARCH_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.SEARCH_MAX_RETRIES
        self.retry_backoff = retry_backoff if retry_backoff is not None else settings.SEARCH_RETRY_BACKOFF_SECONDS
        self.demo_mode = demo_mode if demo_mode is not None else settings.SEARCH_DEMO_MODE

    async def search(
        self,
        query: str,
        engine: str = "google",
        num: int = 5,
        fallback_to_mock: bool = False,
    ) -> SearchResult:
        """
        Execute a search query against SerpApi with bounded retries and honest outcome reporting.
        Production execution never substitutes fabricated companies, domains, or evidence.
        """
        logger.info("SerpApiClient query: '%s' (engine=%s)", query, engine)

        # Demo mode check (strictly isolated from real production investigations)
        if self.demo_mode or self.api_key == "mock_key":
            logger.info("SerpApiClient: demo mode active. Returning isolated demo fixtures.")
            return self._demo_search_results(query)

        # Validate credentials before making network requests (Permanent failure: Do not retry)
        if not self.api_key or not self.api_key.strip():
            logger.warning("SerpApiClient: unconfigured or empty API key. Search unavailable.")
            if fallback_to_mock and self.demo_mode:
                return self._demo_search_results(query)
            return SearchResult(
                query=query,
                provider="serpapi",
                outcome=SearchOutcome.AUTH_FAILURE,
                error="SerpApi API key is unconfigured or empty",
                error_type="AuthenticationError",
                status_code=401,
            )

        params = {
            "q": query,
            "engine": engine,
            "num": num,
            "api_key": self.api_key,
        }

        attempts = 0
        max_attempts = max(1, self.max_retries + 1)
        current_backoff = self.retry_backoff

        while attempts < max_attempts:
            attempts += 1
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(self.base_url, params=params)

                    # HTTP 429 Rate Limit
                    if response.status_code == 429:
                        retry_after_hdr = response.headers.get("Retry-After")
                        retry_after_sec: Optional[float] = None
                        if retry_after_hdr:
                            try:
                                retry_after_sec = float(retry_after_hdr)
                            except ValueError:
                                retry_after_sec = None

                        logger.warning(
                            "SerpApiClient: HTTP 429 rate limit on attempt %d/%d for query '%s'",
                            attempts,
                            max_attempts,
                            query,
                        )

                        # Retry if within bounded budget (<= 2.0s) and attempts remaining
                        if attempts < max_attempts:
                            delay = retry_after_sec if (retry_after_sec is not None and retry_after_sec <= 2.0) else current_backoff
                            if retry_after_sec is not None and retry_after_sec > 2.0:
                                # Budget exceeded; fail immediately
                                return SearchResult(
                                    query=query,
                                    provider="serpapi",
                                    outcome=SearchOutcome.RATE_LIMIT,
                                    error="Rate limit retry delay exceeds task time budget",
                                    error_type="RateLimitError",
                                    status_code=429,
                                )
                            await asyncio.sleep(delay)
                            current_backoff *= 2.0
                            continue

                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.RATE_LIMIT,
                            error="HTTP 429 rate limit exceeded",
                            error_type="RateLimitError",
                            status_code=429,
                        )

                    # HTTP 401/403 Authentication Failure (Permanent: Do not retry)
                    if response.status_code in (401, 403):
                        logger.warning(
                            "SerpApiClient: HTTP %d authentication failure for query '%s'",
                            response.status_code,
                            query,
                        )
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.AUTH_FAILURE,
                            error=f"Invalid API key (status {response.status_code})",
                            error_type="AuthenticationError",
                            status_code=response.status_code,
                        )

                    # HTTP 5xx Server Failure (Transient: retryable)
                    if response.status_code >= 500:
                        logger.warning(
                            "SerpApiClient: HTTP %d provider server error on attempt %d/%d for query '%s'",
                            response.status_code,
                            attempts,
                            max_attempts,
                            query,
                        )
                        if attempts < max_attempts:
                            await asyncio.sleep(current_backoff)
                            current_backoff *= 2.0
                            continue
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.PROVIDER_FAILURE,
                            error=f"Search provider server error (HTTP {response.status_code})",
                            error_type="ProviderServerError",
                            status_code=response.status_code,
                        )

                    # Other client errors (HTTP 400 Bad Request, etc. Permanent: Do not retry)
                    if response.status_code >= 400:
                        logger.warning(
                            "SerpApiClient: HTTP %d client error for query '%s'",
                            response.status_code,
                            query,
                        )
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.PROVIDER_FAILURE,
                            error=f"Search request failed (HTTP {response.status_code})",
                            error_type="ProviderClientError",
                            status_code=response.status_code,
                        )

                    # Parse JSON response
                    try:
                        data = response.json()
                    except (json.JSONDecodeError, ValueError) as json_err:
                        logger.warning(
                            "SerpApiClient: malformed JSON received for query '%s': %s",
                            query,
                            str(json_err),
                        )
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.MALFORMED_RESPONSE,
                            error="Malformed JSON response from search provider",
                            error_type="MalformedResponseError",
                            status_code=200,
                        )

                    # Response must be a JSON object
                    if not isinstance(data, dict):
                        logger.warning("SerpApiClient: response is not a JSON object: %s", type(data).__name__)
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.MALFORMED_RESPONSE,
                            error=f"Expected JSON object, got {type(data).__name__}",
                            error_type="MalformedResponseError",
                            status_code=200,
                        )

                    # Check for SerpApi error payload in HTTP 200 response
                    if "error" in data:
                        raw_err = str(data["error"])
                        safe_err = sanitize_search_text(raw_err, self.api_key)
                        err_low = raw_err.lower()

                        if "hasn't returned any results" in err_low or "no results found" in err_low:
                            logger.info("SerpApiClient: query yielded 0 results ('%s')", query)
                            return SearchResult(
                                query=query,
                                provider="serpapi",
                                outcome=SearchOutcome.ZERO_RESULTS,
                                results=[],
                                knowledge_graph={},
                                search_metadata=data.get("search_metadata"),
                                raw_response=data,
                            )

                        if any(k in err_low for k in ["api key", "invalid api", "unauthorized", "api_key"]):
                            logger.warning("SerpApiClient: auth failure in payload ('%s')", safe_err)
                            return SearchResult(
                                query=query,
                                provider="serpapi",
                                outcome=SearchOutcome.AUTH_FAILURE,
                                error=safe_err,
                                error_type="AuthenticationError",
                                status_code=200,
                            )

                        if any(k in err_low for k in ["rate limit", "exceeded", "out of searches"]):
                            logger.warning("SerpApiClient: rate limit in payload ('%s')", safe_err)
                            return SearchResult(
                                query=query,
                                provider="serpapi",
                                outcome=SearchOutcome.RATE_LIMIT,
                                error=safe_err,
                                error_type="RateLimitError",
                                status_code=200,
                            )

                        logger.warning("SerpApiClient: provider error in payload ('%s')", safe_err)
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.PROVIDER_FAILURE,
                            error=safe_err,
                            error_type="ProviderError",
                            status_code=200,
                        )

                    # Validate consumed fields
                    organic_results = data.get("organic_results")
                    knowledge_graph = data.get("knowledge_graph")

                    if organic_results is not None and not isinstance(organic_results, list):
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.MALFORMED_RESPONSE,
                            error="Expected 'organic_results' to be a list",
                            error_type="MalformedResponseError",
                            status_code=200,
                        )

                    if knowledge_graph is not None and not isinstance(knowledge_graph, dict):
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.MALFORMED_RESPONSE,
                            error="Expected 'knowledge_graph' to be a dictionary",
                            error_type="MalformedResponseError",
                            status_code=200,
                        )

                    # Neither organic_results nor knowledge_graph present
                    if organic_results is None and knowledge_graph is None:
                        metadata = data.get("search_metadata") or data.get("search_information") or {}
                        total = metadata.get("total_results")
                        state = metadata.get("organic_results_state")
                        if total == 0 or state == "Fully empty":
                            return SearchResult(
                                query=query,
                                provider="serpapi",
                                outcome=SearchOutcome.ZERO_RESULTS,
                                results=[],
                                knowledge_graph={},
                                search_metadata=metadata,
                                raw_response=data,
                            )
                        return SearchResult(
                            query=query,
                            provider="serpapi",
                            outcome=SearchOutcome.MALFORMED_RESPONSE,
                            error="Missing both 'organic_results' and 'knowledge_graph' in search response",
                            error_type="MalformedResponseError",
                            status_code=200,
                        )

                    # Distinguish populated vs zero results
                    results_list = organic_results or []
                    kg_dict = knowledge_graph or {}
                    has_usable_results = len(results_list) > 0 or any(bool(v) for v in kg_dict.values())

                    outcome = SearchOutcome.SUCCESS if has_usable_results else SearchOutcome.ZERO_RESULTS

                    logger.info("SerpApiClient: search succeeded with outcome=%s for '%s'", outcome.value, query)
                    return SearchResult(
                        query=query,
                        provider="serpapi",
                        outcome=outcome,
                        results=results_list,
                        knowledge_graph=kg_dict,
                        source=SearchSource.REAL.value,
                        search_metadata=data.get("search_metadata"),
                        raw_response=data,
                    )

            except httpx.TimeoutException as timeout_err:
                logger.warning(
                    "SerpApiClient: timeout (%.1fs) on attempt %d/%d for query '%s'",
                    self.timeout,
                    attempts,
                    max_attempts,
                    query,
                )
                if attempts < max_attempts:
                    await asyncio.sleep(current_backoff)
                    current_backoff *= 2.0
                    continue
                return SearchResult(
                    query=query,
                    provider="serpapi",
                    outcome=SearchOutcome.TIMEOUT,
                    error=f"Search request timed out after {self.timeout}s",
                    error_type="TimeoutError",
                )

            except (httpx.ConnectError, httpx.NetworkError) as net_err:
                safe_err_msg = sanitize_search_text(str(net_err), self.api_key)
                logger.warning(
                    "SerpApiClient: network error on attempt %d/%d for query '%s': %s",
                    attempts,
                    max_attempts,
                    query,
                    safe_err_msg,
                )
                if attempts < max_attempts:
                    await asyncio.sleep(current_backoff)
                    current_backoff *= 2.0
                    continue
                return SearchResult(
                    query=query,
                    provider="serpapi",
                    outcome=SearchOutcome.PROVIDER_FAILURE,
                    error="Connection error reaching search provider",
                    error_type="ConnectionError",
                )

            except asyncio.CancelledError:
                # Always preserve task cancellation
                raise

            except Exception as unhandled_err:
                safe_err_msg = sanitize_search_text(str(unhandled_err), self.api_key)
                logger.warning(
                    "SerpApiClient: unexpected failure for query '%s': %s",
                    query,
                    safe_err_msg,
                )
                return SearchResult(
                    query=query,
                    provider="serpapi",
                    outcome=SearchOutcome.PROVIDER_FAILURE,
                    error="Unexpected search integration failure",
                    error_type="UnexpectedError",
                )

        # Retries exhausted fallback
        return SearchResult(
            query=query,
            provider="serpapi",
            outcome=SearchOutcome.PROVIDER_FAILURE,
            error="Search failed after exhausting all retry attempts",
            error_type="RetriesExhaustedError",
        )

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
