"""Redaction applied by the run service before offer text reaches the investigator.

``CaseInput.redacted_text`` is the only document text that may reach search
queries or hosted models (docs/api-contract.md). The investigator needs the
employer, recruiter contact details, role and links to do its job, so those stay.
What goes are identifiers that belong to the candidate and are never useful to a
search: government ID numbers, bank/card numbers and secrets such as OTPs.
"""

import re
from typing import List, Tuple

from app.services.agents.scam_classifier import sanitize_and_redact_secrets

_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Aadhaar: 12 digits, commonly grouped 4-4-4.
    (re.compile(r"(?<![\d+])\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"), "[REDACTED_ID]"),
    # PAN: AAAAA9999A
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[REDACTED_ID]"),
    # Passport (India): one letter + 7 digits, only when labelled.
    (re.compile(r"(?i)(passport\s*(?:no\.?|number)?\s*[:#-]?\s*)[A-Z]\d{7}\b"), r"\1[REDACTED_ID]"),
    # Card numbers: 13-19 digits, optionally grouped.
    (re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{1,7}(?!\d)"), "[REDACTED_CARD]"),
    # Bank account numbers, only when labelled (bare long numbers may be references).
    (
        re.compile(r"(?i)((?:a/c|acct|account)\s*(?:no\.?|number)?\s*[:#-]?\s*)\d{9,18}\b"),
        r"\1[REDACTED_ACCOUNT]",
    ),
]


def redact_case_text(text: str) -> str:
    """Return offer text safe to hand to the investigator."""
    redacted = sanitize_and_redact_secrets(text or "")
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
