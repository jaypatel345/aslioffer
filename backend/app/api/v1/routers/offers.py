import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlmodel import Session, select
from app.db.session import get_session
from app.db.models.offer import Offer
from app.db.models.evidence import Evidence
from app.schemas.offer import OfferCreate, OfferRead, OfferUploadResponse
from app.schemas.analysis import VerificationReport, RiskLevel
from app.schemas.contract import ErrorResponse
from app.services.extractor.entity_extractor import EntityExtractor
from app.services.agents.company_agent import CompanyAgent
from app.services.agents.recruiter_agent import RecruiterAgent
from app.services.agents.salary_agent import SalaryAgent
from app.services.agents.scam_agent import ScamAgent
from app.services.risk.risk_engine import RiskEngine
from app.services.risk.verdict_reasoner import VerdictReasoner
from app.services.report.report_generator import ReportGenerator
from app.core.logging import logger

router = APIRouter(tags=["Offers"])

SAMPLE_TITLE_PREFIX = "Sample: "


def _get_offer_or_404(session: Session, offer_id: int) -> Offer:
    """Return the requested offer or raise 404. Never substitutes another case."""
    offer = session.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Offer {offer_id} not found.")
    return offer

extractor = EntityExtractor()
company_agent = CompanyAgent()
recruiter_agent = RecruiterAgent()
salary_agent = SalaryAgent()
scam_agent = ScamAgent()
risk_engine = RiskEngine()
verdict_reasoner = VerdictReasoner()
report_generator = ReportGenerator()


@router.post("/offers/upload", response_model=OfferUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_offer(
    title: Optional[str] = Form(None),
    source_type: str = Form("text"),
    raw_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    sample: bool = Form(False),
    session: Session = Depends(get_session),
):
    """
    Upload an offer letter (PDF, screenshot, email text, or direct message).
    Extracts initial text and persists an Offer record ready for investigation.

    ``sample=true`` marks a case started from a built-in preset: it is investigated
    like any other case but its title is prefixed with "Sample: " so it can never
    be mistaken for a user's own offer.
    """
    content = raw_content or ""
    offer_title = title or "Job Offer Verification"

    if file:
        file_bytes = await file.read()
        filename = file.filename or "uploaded_file"
        mime = file.content_type or ("application/pdf" if filename.lower().endswith(".pdf") else "image/png")
        source_type = "pdf" if filename.lower().endswith(".pdf") else "screenshot"
        offer_title = title or f"Offer from {filename}"
        reason = None
        try:
            doc_result = await extractor.extract_from_document(file_bytes, mime)
            content = (doc_result.get("ocr_text") or "").strip()
            reason = doc_result.get("error")
        except Exception as e:
            logger.warning("Document extraction failed (%s)", str(e))
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

    if not content:
        raise HTTPException(status_code=400, detail="Either file or raw_content must be provided.")

    if sample and not offer_title.startswith(SAMPLE_TITLE_PREFIX):
        offer_title = SAMPLE_TITLE_PREFIX + offer_title

    new_offer = Offer(
        title=offer_title,
        source_type=source_type,
        raw_content=content,
        status="PENDING",
    )
    session.add(new_offer)
    session.commit()
    session.refresh(new_offer)

    logger.info("Created new offer record with ID %d", new_offer.id)

    return OfferUploadResponse(
        offer_id=new_offer.id,
        title=new_offer.title,
        status=new_offer.status,
        message="Offer received successfully. Ready for agent investigation.",
    )


@router.get("/offers/{id}", response_model=OfferRead, responses={404: {"model": ErrorResponse}})
async def get_offer(id: int, session: Session = Depends(get_session)):
    """Retrieve an offer by ID."""
    return _get_offer_or_404(session, id)


@router.get("/offers/{id}/report", response_model=VerificationReport, responses={404: {"model": ErrorResponse}})
async def get_offer_report(id: int, session: Session = Depends(get_session)):
    """
    Retrieve or compute the forensic investigation report for an offer.
    Runs extraction, agents, risk engine, and compiles verifiable findings.
    Unknown offer IDs return 404 before any extraction or search runs.
    """
    # A missing case is a 404 — never a built-in sample letter analysed in its place.
    offer = _get_offer_or_404(session, id)
    raw_content = offer.raw_content
    offer_title = offer.title

    # Step 1: Entity Extraction (Gemini structured extraction with regex fallback)
    extracted_data = await extractor.extract_entities(raw_content)
    entities = extracted_data.to_extracted_entities()

    # Step 2: Investigation Agents — run concurrently; they share no state and
    # each spends nearly all its time waiting on SerpApi.
    company_name = entities.company_name or "Unknown Company"
    finding_comp, finding_rec, finding_sal, finding_scam = await asyncio.gather(
        company_agent.investigate(company_name),
        recruiter_agent.investigate(
            company_name=company_name,
            recruiter_name=entities.recruiter_name,
            recruiter_email=entities.recruiter_email,
            recruiter_phone=entities.recruiter_phone,
            agency_name=getattr(entities, "agency_name", None),
        ),
        salary_agent.investigate(
            company_name=company_name,
            role_title=entities.role_title,
            offered_salary=entities.offered_salary,
        ),
        scam_agent.investigate(
            company_name=company_name,
            demanded_fee=entities.demanded_fee,
            payment_method=entities.payment_method,
            flags=entities.flags,
            raw_text=raw_content,
        ),
    )

    findings = [finding_comp, finding_rec, finding_sal, finding_scam]

    # Step 3: Risk Engine (Deterministic score calculation)
    risk_score, initial_risk_level, red_flags, green_flags = risk_engine.compute_risk(findings)

    # Step 4: Verdict Reasoner (Evidence-aware verdict determination)
    verdict_result = verdict_reasoner.evaluate(
        company_result=finding_comp,
        recruiter_result=finding_rec,
        salary_result=finding_sal,
        scam_result=finding_scam,
        initial_risk_score=risk_score,
        initial_risk_level=initial_risk_level,
    )
    final_verdict = verdict_result.verdict

    # Step 5: Update offer status in DB
    offer.risk_score = risk_score
    offer.risk_level = final_verdict.value
    offer.status = "COMPLETED"
    session.add(offer)
    session.commit()

    # Step 6: Generate Report
    report = report_generator.generate(
        offer_id=id,
        title=offer_title,
        risk_score=risk_score,
        risk_level=final_verdict,
        extracted_entities=entities,
        findings=findings,
        red_flags=red_flags,
        green_flags=green_flags,
        reason_details=verdict_result.reason_details,
        structured_assessment=verdict_result.structured_assessment,
    )

    return report
