from datetime import timedelta, timezone
from pathlib import PurePath
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Response, UploadFile, status
from sqlmodel import Session

from app.core.config import settings
from app.core.logging import logger
from app.db.models.offer import Offer
from app.db.session import get_session
from app.schemas.contract import CONTRACT_VERSION, CaseInput, ErrorResponse, RunSnapshot
from app.schemas.offer import OfferRead, OfferUploadResponse
from app.schemas.runs import ClaimPreview
from app.services.extractor.entity_extractor import EntityExtractor
from app.services.investigation.claim_builder import ClaimBuilder
from app.services.privacy.access import CASE_TOKEN_HEADER, hash_case_token, new_case_token, token_matches
from app.services.privacy.redaction import redact_case_text
from app.services.runs import run_service

router = APIRouter(tags=["Offers"])

SAMPLE_TITLE_PREFIX = "Sample: "
MAX_TITLE_CHARS = 200

# Accepted uploads: extension -> (source_type, MIME sent to the extractor).
ALLOWED_UPLOADS = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("screenshot", "image/png"),
    ".jpg": ("screenshot", "image/jpeg"),
    ".jpeg": ("screenshot", "image/jpeg"),
    ".webp": ("screenshot", "image/webp"),
}
ALLOWED_TEXT_SOURCE_TYPES = {"text", "email"}

NOT_FOUND = {404: {"model": ErrorResponse}}

extractor = EntityExtractor()


def get_case(
    id: int,
    session: Session = Depends(get_session),
    x_case_token: Optional[str] = Header(None, alias=CASE_TOKEN_HEADER),
) -> Offer:
    """The requested case, or 404. A missing or wrong token is the same 404 as an
    unknown ID, so neither case existence nor another case is ever revealed."""
    offer = session.get(Offer, id)
    if offer is None or not token_matches(x_case_token, offer.access_token_hash):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Offer {id} not found.")
    return offer


def _too_large(detail: str) -> HTTPException:
    return HTTPException(status_code=413, detail=detail)


async def _read_bounded(file: UploadFile) -> bytes:
    data = await file.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise _too_large(f"File is larger than {settings.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    return data


@router.post(
    "/offers/upload",
    response_model=OfferUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse},
               415: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def upload_offer(
    title: Optional[str] = Form(None),
    source_type: str = Form("text"),
    raw_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    sample: bool = Form(False),
    session: Session = Depends(get_session),
):
    """
    Upload an offer letter (PDF or image) or paste an email/message.

    Returns the case ID and a one-time ``access_token``; every later request for
    the case must send it as the ``X-Case-Token`` header. No search runs here.

    ``sample=true`` marks a case started from a built-in preset: it is investigated
    like any other case but its title is prefixed with "Sample: " so it can never
    be mistaken for a user's own offer.
    """
    content = raw_content or ""
    offer_title = (title or "Job Offer Verification").strip()[:MAX_TITLE_CHARS] or "Job Offer Verification"
    if source_type not in ALLOWED_TEXT_SOURCE_TYPES:
        source_type = "text"

    if file:
        filename = PurePath(file.filename or "upload").name
        suffix = PurePath(filename).suffix.lower()
        if suffix not in ALLOWED_UPLOADS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported file type. Upload a PDF, PNG, JPG or WEBP file, or paste the text.",
            )
        source_type, mime = ALLOWED_UPLOADS[suffix]
        file_bytes = await _read_bounded(file)
        offer_title = (title or f"Offer from {filename}")[:MAX_TITLE_CHARS]
        reason = None
        try:
            doc_result = await extractor.extract_from_document(file_bytes, mime)
            content = (doc_result.get("ocr_text") or "").strip()
            reason = doc_result.get("error")
        except Exception as e:
            logger.warning("Document extraction failed (%s)", type(e).__name__)
            content = ""
            reason = extractor._describe_failure(e)

        # Refuse rather than analyse noise: a verdict derived from unreadable bytes
        # is indistinguishable from a real one to the person reading the report.
        if not content:
            raise HTTPException(
                status_code=422,
                detail=f"Could not read any text from '{filename}'. "
                + (reason or "The file format could not be parsed. Paste the message text instead."),
            )

    content = content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Either file or raw_content must be provided.")
    if len(content) > settings.MAX_TEXT_CHARS:
        raise _too_large(
            f"Offer text is longer than {settings.MAX_TEXT_CHARS:,} characters. Paste only the offer itself."
        )

    if sample and not offer_title.startswith(SAMPLE_TITLE_PREFIX):
        offer_title = SAMPLE_TITLE_PREFIX + offer_title

    token = new_case_token()
    new_offer = Offer(
        title=offer_title,
        source_type=source_type,
        raw_content=content,
        status="PENDING",
        access_token_hash=hash_case_token(token),
    )
    session.add(new_offer)
    session.commit()
    session.refresh(new_offer)

    logger.info("Created case %d (%s, %d chars)", new_offer.id, source_type, len(content))

    created = new_offer.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return OfferUploadResponse(
        offer_id=new_offer.id,
        title=new_offer.title,
        status=new_offer.status,
        message="Offer received. Review the extracted claims, then start the investigation.",
        access_token=token,
        expires_at=created + timedelta(days=settings.CASE_RETENTION_DAYS),
    )


@router.get("/offers/{id}", response_model=OfferRead, responses=NOT_FOUND)
async def get_offer(offer: Offer = Depends(get_case)):
    """Retrieve an offer by ID."""
    return offer


@router.delete("/offers/{id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_offer(offer: Offer = Depends(get_case), session: Session = Depends(get_session)):
    """Permanently delete the case: offer text, claims, runs and reports."""
    run_service.delete_case(session, offer)
    logger.info("Case %d deleted by its owner", offer.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def build_claim_preview(offer: Offer) -> ClaimPreview:
    text = redact_case_text(offer.raw_content)
    case_input = CaseInput(
        contract_version=CONTRACT_VERSION,
        case_id=offer.id,
        run_id=f"preview_{offer.id}",
        source_type=offer.source_type if offer.source_type in ("pdf", "screenshot", "email", "text") else "text",
        redacted_text=text,
    )
    claims, _, _ = ClaimBuilder().build_claims(case_input)
    return ClaimPreview(case_id=offer.id, text=text, claims=claims)


@router.get("/offers/{id}/claims", response_model=ClaimPreview, responses=NOT_FOUND)
async def get_claims(offer: Offer = Depends(get_case)):
    """
    Claims extracted from the offer for the user to review before investigating.
    Local and deterministic: no search or hosted-model call is made.
    """
    return build_claim_preview(offer)


@router.get(
    "/offers/{id}/report",
    response_model=RunSnapshot,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def get_offer_report(offer: Offer = Depends(get_case), session: Session = Depends(get_session)):
    """
    The latest finished report for this case (a COMPLETED or PARTIAL RunSnapshot).
    Reads the stored snapshot only; it never starts extraction or search.
    409 if the case exists but has no report yet.
    """
    row = run_service.latest_report_run(session, offer.id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Offer {offer.id} has no finished report yet. Start an investigation first.",
        )
    return run_service.to_snapshot(row)


@router.get("/offers/{id}/runs", response_model=List[RunSnapshot], responses=NOT_FOUND)
async def get_offer_runs(offer: Offer = Depends(get_case), session: Session = Depends(get_session)):
    """Every run for this case, newest version first. Read-only."""
    return [run_service.to_snapshot(r) for r in run_service.list_runs(session, offer.id)]
