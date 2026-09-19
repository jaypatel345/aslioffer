from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from app.db.session import get_session
from app.db.models.offer import Offer
from app.schemas.analysis import AnalysisRequest, VerificationReport
from app.api.v1.routers.offers import get_offer_report
from app.core.logging import logger

router = APIRouter(tags=["Analysis"])


@router.post("/analysis/run", response_model=VerificationReport)
async def run_analysis(
    request: AnalysisRequest,
    session: Session = Depends(get_session),
):
    """
    Triggers multi-agent forensic analysis on an uploaded offer.
    Coordinates Company, Recruiter, Salary, and Scam agents to generate an evidence-backed report.
    """
    logger.info("Triggering forensic analysis pipeline for offer_id=%d", request.offer_id)
    return await get_offer_report(id=request.offer_id, session=session)
