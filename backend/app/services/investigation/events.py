"""
Event emission manager for investigation pipeline (Task 10).

Emits RunEvent updates with strictly increasing sequences and public-safe messages.
Guarantees callback failures never alter investigation verdicts, while propagating
caller cancellation cleanly.
"""

import asyncio
from datetime import datetime, timezone
import re
from typing import Any, Callable, List, Optional

from app.schemas.contract import EventStatus, RunEvent
from app.core.logging import logger


def sanitize_public_message(message: str) -> str:
    """
    Strips provider keys, tokens, or sensitive internal details from user-facing event messages.
    """
    if not message:
        return ""
    # Strip API keys or query params
    clean = re.sub(r"(?i)api[_\-]?key[=:][^\s&]+", "[KEY_REDACTED]", message)
    clean = re.sub(r"(?i)token[=:][^\s&]+", "[TOKEN_REDACTED]", clean)
    clean = re.sub(r"(?i)bearer\s+[A-Za-z0-9_\-\.]+", "[TOKEN_REDACTED]", clean)
    # Ensure word boundaries don't leak "api_key" substring
    clean = re.sub(r"(?i)api_key", "key", clean)
    return clean.strip()


class EventEmitter:
    """
    Manages monotonic sequence ordering and safe async delivery of RunEvent records.
    """

    def __init__(self, run_id: str, emit_fn: Optional[Callable[[RunEvent], Any]] = None):
        self.run_id = run_id
        self.emit_fn = emit_fn
        self.sequence = 0
        self.emitted_events: List[RunEvent] = []

    async def emit(self, step: str, status: EventStatus, message: str) -> Optional[RunEvent]:
        """
        Emits a validated RunEvent. Swallows callback errors (logging a warning)
        without changing the investigation verdict, but re-raises CancelledError.
        """
        clean_msg = sanitize_public_message(message)
        event = RunEvent(
            run_id=self.run_id,
            sequence=self.sequence,
            step=step,
            status=status,
            public_message=clean_msg,
            timestamp=datetime.now(timezone.utc),
        )
        self.sequence += 1
        self.emitted_events.append(event)

        if self.emit_fn is not None:
            try:
                res = self.emit_fn(event)
                if asyncio.iscoroutine(res):
                    await res
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Event emission callback error for step %s: %s", step, exc)

        return event
