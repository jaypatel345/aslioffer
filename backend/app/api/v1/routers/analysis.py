from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Response, status
from sqlmodel import Session

from app.core.logging import logger
from app.db.models.offer import Offer
from app.db.models.run import InvestigationRun
from app.db.session import get_session
from app.schemas.contract import CONTRACT_VERSION, CaseInput, ErrorResponse, RunSnapshot
from app.schemas.runs import RunRequest
from app.services.investigation.claim_builder import ClaimBuilder
from app.services.privacy.access import CASE_TOKEN_HEADER, token_matches
from app.services.privacy.redaction import redact_case_text
from app.services.runs import run_service

router = APIRouter(tags=["Analysis"])


def _validate_confirmed_claims(offer: Offer, request: RunRequest) -> None:
    """Reject confirmations the investigator would refuse, before a run is created."""
    if not request.confirmed_claims:
        return
    try:
        ClaimBuilder().build_claims(
            CaseInput(
                contract_version=CONTRACT_VERSION,
                case_id=offer.id,
                run_id=f"validate_{offer.id}",
                source_type="text",
                redacted_text=redact_case_text(offer.raw_content),
                confirmed_claims=request.confirmed_claims,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid claim confirmation: {exc}")


@router.post(
    "/analysis/run",
    response_model=RunSnapshot,
    responses={202: {"model": RunSnapshot}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def run_analysis(
    request: RunRequest,
    response: Response,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    x_case_token: Optional[str] = Header(None, alias=CASE_TOKEN_HEADER),
):
    """
    Start (or reuse) an investigation for an offer and return its RunSnapshot.

    * An active run for the case is returned as is: no second search is started.
    * Without ``force_refresh``, a finished report for the same inputs is reused.
    * With ``force_refresh``, a new version is created and the previous one kept.

    202 when a new run was queued, 200 when an existing run was returned. Poll
    ``GET /analysis/runs/{run_id}`` for progress. Unknown offers return 404.
    """
    offer = session.get(Offer, request.offer_id)
    if offer is None or not token_matches(x_case_token, offer.access_token_hash):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Offer {request.offer_id} not found.")

    _validate_confirmed_claims(offer, request)
    row, created = run_service.request_run(session, offer, request.confirmed_claims, request.force_refresh)
    if created:
        logger.info("Queued run %s (case %d, version %d)", row.run_id, offer.id, row.version)
        background.add_task(run_service.execute_run, row.run_id)
        response.status_code = status.HTTP_202_ACCEPTED
    return run_service.to_snapshot(row)


@router.get("/analysis/runs/{run_id}", response_model=RunSnapshot, responses={404: {"model": ErrorResponse}})
async def get_run(
    run_id: str,
    session: Session = Depends(get_session),
    x_case_token: Optional[str] = Header(None, alias=CASE_TOKEN_HEADER),
):
    """Current state of a run, backed by the events the investigator actually emitted."""
    row = session.get(InvestigationRun, run_id)
    offer = session.get(Offer, row.case_id) if row is not None else None
    if row is None or offer is None or not token_matches(x_case_token, offer.access_token_hash):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run {run_id} not found.")
    return run_service.to_snapshot(row)
