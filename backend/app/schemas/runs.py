"""HTTP request/response shapes for the run service (J3/J4).

These wrap contract-v1 objects (``app.schemas.contract``) for the HTTP layer;
they do not change the investigator contract itself.
"""

from typing import List

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.contract import Claim, ConfirmedClaim


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: int
    force_refresh: bool = False
    # Decisions from the claim review screen. Empty means "investigate what was extracted".
    confirmed_claims: List[ConfirmedClaim] = Field(default_factory=list)


class ClaimPreview(BaseModel):
    """Claims extracted locally from the redacted offer text, for the user to review.

    Built without any search or hosted-model call. ``text`` is the redacted text
    the claims' offsets refer to.
    """

    case_id: int
    text: str
    claims: List[Claim]
