"""
Investigation budget and concurrency configuration for AsliOffer (Task 11).

Defines bounded limits for underlying search operations, adaptive follow-ups,
concurrent in-flight provider calls, and elapsed execution time.
"""
from dataclasses import dataclass, field
import asyncio
import time
import math
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class InvestigationBudget:
    """
    Validated budget and execution limits for an investigation run.

    Distinguishes search operations from physical HTTP retries:
    - `max_search_calls`: Maximum unique admitted search operations across initial
      and adaptive checks.
    - `max_followup_calls`: Maximum admitted search operations for adaptive planning.
    - `max_concurrent_calls`: Maximum in-flight external provider calls running in parallel.
    - `deadline_seconds`: Monotonic elapsed time limit for all external search operations.

    Note: An underlying client (e.g. SerpApiClient) may execute internal HTTP retries
    for a single admitted operation on transient 5xx errors; that is bounded by the client's
    configured retry policy and the remaining investigation deadline.
    """
    max_search_calls: int = 8
    max_followup_calls: int = 3
    max_concurrent_calls: int = 3
    deadline_seconds: float = 15.0

    def __post_init__(self):
        for name in ('max_search_calls', 'max_followup_calls', 'max_concurrent_calls'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if self.max_search_calls < 1 or self.max_followup_calls < 0 or self.max_concurrent_calls < 1:
            raise ValueError("Call limits must be positive, except follow-ups may be zero")
        if self.max_followup_calls > self.max_search_calls:
            self.max_followup_calls = self.max_search_calls
        if isinstance(self.deadline_seconds, bool) or not isinstance(self.deadline_seconds, (int, float)) or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be finite and positive")


class BudgetManager:
    """
    Coroutine-safe admission controller for external search operations.

    Enforces:
    - Atomic reservation immediately prior to provider invocation.
    - Zero allowance consumed by cache hits or budget-denied requests.
    - Exactly one allowance consumed by coalesced concurrent identical requests.
    - Hard monotonic deadline enforcement across external operations.
    - Short-circuit suppression of follow-ups upon authentication/configuration failure.
    """

    def __init__(self, budget: Optional[InvestigationBudget] = None):
        self.budget = budget or InvestigationBudget()
        self._lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(self.budget.max_concurrent_calls)
        self._start_time = time.monotonic()
        self.deadline_ts = self._start_time + self.budget.deadline_seconds

        self.admitted_total_calls: int = 0
        self.admitted_followup_calls: int = 0
        self.denied_calls: List[Dict[str, Any]] = []
        self.auth_failure_detected: bool = False

    @property
    def remaining_seconds(self) -> float:
        """Returns remaining seconds before the investigation deadline."""
        return max(0.0, self.deadline_ts - time.monotonic())

    @property
    def is_deadline_exceeded(self) -> bool:
        """Returns True if the monotonic elapsed deadline has expired."""
        return time.monotonic() >= self.deadline_ts

    async def try_admit(
        self,
        is_followup: bool = False,
        query: str = "",
        step: str = "",
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Atomically evaluates admission immediately before an underlying provider call.

        Returns:
            (admitted: bool, denial_reason: Optional[str], denial_type: Optional[str])
        """
        async with self._lock:
            # 1. Auth failure suppression: further searches are futile
            if self.auth_failure_detected:
                reason = "Search provider authentication or configuration failure suppresses further searches"
                denial_type = "AUTH_FAILURE"
                self.denied_calls.append({"query": query, "step": step, "reason": reason, "type": denial_type})
                return False, reason, denial_type

            # 2. Monotonic deadline check
            if self.is_deadline_exceeded:
                reason = "Investigation elapsed deadline expired"
                denial_type = "DEADLINE_EXCEEDED"
                self.denied_calls.append({"query": query, "step": step, "reason": reason, "type": denial_type})
                return False, reason, denial_type

            # 3. Overall call budget check
            if self.admitted_total_calls >= self.budget.max_search_calls:
                reason = f"Total search call budget ({self.budget.max_search_calls}) reached"
                denial_type = "BUDGET_EXCEEDED"
                self.denied_calls.append({"query": query, "step": step, "reason": reason, "type": denial_type})
                return False, reason, denial_type

            # 4. Adaptive follow-up budget check
            if is_followup and self.admitted_followup_calls >= self.budget.max_followup_calls:
                reason = f"Adaptive follow-up search budget ({self.budget.max_followup_calls}) reached"
                denial_type = "FOLLOWUP_BUDGET_EXCEEDED"
                self.denied_calls.append({"query": query, "step": step, "reason": reason, "type": denial_type})
                return False, reason, denial_type

            # Admitted atomically
            self.admitted_total_calls += 1
            if is_followup:
                self.admitted_followup_calls += 1
            return True, None, None

    def record_auth_failure(self):
        """Signals that an auth/credential failure occurred, suppressing subsequent queries."""
        self.auth_failure_detected = True
