"""Per-case access tokens.

Offer IDs are sequential, so the ID alone must never be enough to read a case.
Upload returns a random token once; only its SHA-256 hash is stored. Every
case-scoped request carries the token in the ``X-Case-Token`` header. A missing
or wrong token gets the same 404 as an unknown ID, so case existence does not leak.
"""

import hashlib
import hmac
import secrets
from typing import Optional

CASE_TOKEN_HEADER = "X-Case-Token"


def new_case_token() -> str:
    return secrets.token_urlsafe(32)


def hash_case_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: Optional[str], stored_hash: Optional[str]) -> bool:
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(hash_case_token(token), stored_hash)
