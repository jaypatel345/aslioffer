import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlmodel import Session, select
from app.db.session import get_session
from app.db.models.offer import Offer
from app.db.models.evidence import Evidence
from app.schemas.offer import OfferCreate, OfferRead, OfferUploadResponse
from app.schemas.analysis import VerificationReport, RiskLevel
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
    session: Session = Depends(get_session),
):
    """
    Upload an offer letter (PDF, screenshot, email text, or direct message).
    Extracts initial text and persists an Offer record ready for investigation.
    """
    content = raw_content or ""
    offer_title = title or "Job Offer Verification"

    if file:
        file_bytes = await file.read()
        filename = file.filename or "uploaded_file"
        mime = file.content_type or ("application/pdf" if filename.lower().endswith(".pdf") else "image/png")
        source_type = "pdf" if filename.lower().endswith(".pdf") else "screenshot"
        offer_title = title or f"Offer from {filename}"
        try:
            doc_result = await extractor.extract_from_document(file_bytes, mime)
            content = doc_result.get("ocr_text") or f"Extracted from {filename}"
        except Exception as e:
            logger.warning("Document extraction failed (%s), using raw text fallback", str(e))
            content = f"Binary content from {filename} ({len(file_bytes)} bytes)"

    if not content:
        raise HTTPException(status_code=400, detail="Either file or raw_content must be provided.")

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


@router.get("/offers/{id}", response_model=OfferRead)
async def get_offer(id: int, session: Session = Depends(get_session)):
    """Retrieve an offer by ID."""
    offer = session.get(Offer, id)
    if not offer:
        # Fallback mock for demo convenience if ID doesn't exist
        return OfferRead(
            id=id,
            title="TCS Associate Software Engineer Offer Letter",
            source_type="pdf",
            raw_content="Mock offer letter content for demonstration.",
            risk_score=0.88,
            status="COMPLETED",
            risk_level="HIGH_RISK",
            created_at=Offer(title="mock", source_type="text", raw_content="mock").created_at,
        )
    return offer


@router.get("/offers/{id}/report", response_model=VerificationReport)
async def get_offer_report(id: int, session: Session = Depends(get_session)):
    """
    Retrieve or compute the forensic investigation report for an offer.
    Runs extraction, agents, risk engine, and compiles verifiable findings.
    """
    offer = session.get(Offer, id)
    raw_content = offer.raw_content if offer else (
        "Dear Candidate, Congratulations on being selected for Tata Consultancy Services as a "
        "Graduate Software Trainee. Your package is INR 8.5 LPA. Kindly deposit INR 15,000 as "
        "refundable laptop security deposit via UPI to tcs-recruiter@upi. Contact HR: rohit.tcs@gmail.com."
    )
    offer_title = offer.title if offer else "Offer Letter Verification"

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

    # Step 5: Update offer status in DB if exists
    if offer:
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
    )

    return report
