import logging
import re
import sys

# Offer letters carry personal data. Logs are not a place to keep it, so every
# record passing through the "aslioffer" logger is scrubbed of the identifiers
# below before it is written, whatever the call site passed in.
_SCRUB_PATTERNS = [
    (re.compile(r"(?i)(api_key|apikey|token|secret|password)=([^&\s'\"]+)"), r"\1=[REDACTED]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"(?<![\w-])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\w-])"), "[PHONE]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[ID_NUMBER]"),
]


def scrub_log_text(text: str) -> str:
    for pattern, replacement in _SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class ScrubbingFilter(logging.Filter):
    """Redacts emails, phone numbers, ID numbers and credentials from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = scrub_log_text(message)
        record.args = None
        return True


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("aslioffer")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if not any(isinstance(f, ScrubbingFilter) for f in logger.filters):
        logger.addFilter(ScrubbingFilter())

    return logger


logger = setup_logging()
