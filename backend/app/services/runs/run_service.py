"""Run service (J3): persisted investigation runs served as contract-v1 RunSnapshots.

Rules (docs/api-contract.md):

* ``POST /analysis/run`` creates or reuses a run. It never blocks on the
  investigation; the run executes in the background and the client polls.
* An active (QUEUED/RUNNING) run for a case is always reused, so repeated clicks
  or a refresh while a run is in progress never multiply search calls.
* Without ``force_refresh`` a finished run with a report and the same inputs is
  reused. ``force_refresh`` creates version n+1 and keeps version n.
* Reading a report only reads stored snapshots; nothing here is called on GET.
* Tool failures come back inside the report (status PARTIAL). Only unexpected
  exceptions or the run timeout mark a run FAILED, and a failure never becomes a
  demo or sample report.

Deduplication relies on the check-then-insert in ``request_run`` running without
an ``await`` in between, which makes it atomic within one process. Run the API
with a single worker process (the default for ``uvicorn app.main:app``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlmodel import Session, select

from app.core.config import settings
from app.core.logging import logger
from app.db.models.evidence import Evidence
from app.db.models.offer import Offer
from app.db.models.run import InvestigationRun
from app.db import session as db_session
from app.schemas.contract import (
    CONTRACT_VERSION,
    CaseInput,
    ConfirmedClaim,
    EventStatus,
    InvestigationResult,
    RunError,
    RunEvent,
    RunSnapshot,
    RunStatus,
    SourceType,
)
from app.services.investigation.pipeline import investigate_case
from app.services.privacy.redaction import redact_case_text

ACTIVE_STATUSES = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
REPORT_STATUSES = (RunStatus.COMPLETED.value, RunStatus.PARTIAL.value)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    # SQLite drops tzinfo on the way back out; every stored time is UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def compute_input_hash(text: str, confirmed_claims: List[ConfirmedClaim]) -> str:
    payload = {
        "contract_version": CONTRACT_VERSION,
        "text": text,
        "confirmed_claims": sorted(
            (c.model_dump(mode="json") for c in confirmed_claims), key=lambda c: c["claim_id"]
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def to_snapshot(row: InvestigationRun) -> RunSnapshot:
    report = InvestigationResult.model_validate_json(row.report_json) if row.report_json else None
    return RunSnapshot(
        contract_version=CONTRACT_VERSION,
        run_id=row.run_id,
        case_id=row.case_id,
        version=row.version,
        previous_run_id=row.previous_run_id,
        status=RunStatus(row.status),
        created_at=_as_utc(row.created_at),
        started_at=_as_utc(row.started_at),
        finished_at=_as_utc(row.finished_at),
        events=[RunEvent.model_validate(e) for e in json.loads(row.events_json or "[]")],
        report=report,
        errors=[RunError.model_validate(e) for e in json.loads(row.errors_json or "[]")],
    )


def _case_runs(session: Session, case_id: int) -> List[InvestigationRun]:
    return list(
        session.exec(
            select(InvestigationRun)
            .where(InvestigationRun.case_id == case_id)
            .order_by(InvestigationRun.version.desc())
        ).all()
    )


def list_runs(session: Session, case_id: int) -> List[InvestigationRun]:
    return _case_runs(session, case_id)


def latest_report_run(session: Session, case_id: int) -> Optional[InvestigationRun]:
    """The newest run that carries a report. Never starts anything."""
    for row in _case_runs(session, case_id):
        if row.status in REPORT_STATUSES:
            return row
    return None


def request_run(
    session: Session,
    offer: Offer,
    confirmed_claims: List[ConfirmedClaim],
    force_refresh: bool,
) -> Tuple[InvestigationRun, bool]:
    """Return (run, created). ``created`` is True only when a new run must be started."""
    input_hash = compute_input_hash(offer.raw_content, confirmed_claims)
    runs = _case_runs(session, offer.id)

    active = next((r for r in runs if r.status in ACTIVE_STATUSES), None)
    if active is not None:
        return active, False

    if not force_refresh:
        reusable = next(
            (r for r in runs if r.status in REPORT_STATUSES and r.input_hash == input_hash), None
        )
        if reusable is not None:
            return reusable, False

    latest = runs[0] if runs else None
    row = InvestigationRun(
        run_id=f"run_{uuid.uuid4().hex}",
        case_id=offer.id,
        version=(latest.version + 1) if latest else 1,
        previous_run_id=latest.run_id if latest else None,
        status=RunStatus.QUEUED.value,
        input_hash=input_hash,
        confirmed_claims_json=json.dumps([c.model_dump(mode="json") for c in confirmed_claims]),
        created_at=_utcnow(),
    )
    session.add(row)
    offer.status = "PROCESSING"
    session.add(offer)
    session.commit()
    session.refresh(row)
    return row, True


def _source_type(value: str) -> SourceType:
    try:
        return SourceType(value)
    except ValueError:
        return SourceType.TEXT


def _append_event(run_id: str, event: RunEvent) -> None:
    with Session(db_session.engine) as session:
        row = session.get(InvestigationRun, run_id)
        if row is None:
            return
        events = json.loads(row.events_json or "[]")
        events.append(event.model_dump(mode="json"))
        row.events_json = json.dumps(events)
        session.add(row)
        session.commit()


def _finish(
    run_id: str,
    status: RunStatus,
    report: Optional[InvestigationResult],
    errors: List[RunError],
    final_event: Optional[Tuple[str, EventStatus, str]] = None,
) -> None:
    with Session(db_session.engine) as session:
        row = session.get(InvestigationRun, run_id)
        if row is None:
            return  # case deleted while the run was in flight
        if final_event is not None:
            events = json.loads(row.events_json or "[]")
            sequence = (events[-1]["sequence"] + 1) if events else 0
            step, ev_status, message = final_event
            events.append(
                RunEvent(
                    run_id=run_id,
                    sequence=sequence,
                    step=step,
                    status=ev_status,
                    public_message=message,
                    timestamp=_utcnow(),
                ).model_dump(mode="json")
            )
            row.events_json = json.dumps(events)
        row.status = status.value
        row.finished_at = _utcnow()
        row.report_json = report.model_dump_json() if report is not None else None
        row.errors_json = json.dumps([e.model_dump(mode="json") for e in errors])
        session.add(row)

        offer = session.get(Offer, row.case_id)
        if offer is not None:
            offer.status = "FAILED" if status == RunStatus.FAILED else "COMPLETED"
            session.add(offer)
        session.commit()


async def execute_run(run_id: str, search_client=None) -> None:
    """Run the investigator for a QUEUED run and persist the outcome."""
    with Session(db_session.engine) as session:
        row = session.get(InvestigationRun, run_id)
        if row is None or row.status != RunStatus.QUEUED.value:
            return
        offer = session.get(Offer, row.case_id)
        if offer is None:
            return
        case_input = CaseInput(
            contract_version=CONTRACT_VERSION,
            case_id=offer.id,
            run_id=run_id,
            source_type=_source_type(offer.source_type),
            redacted_text=redact_case_text(offer.raw_content),
            confirmed_claims=[ConfirmedClaim.model_validate(c) for c in json.loads(row.confirmed_claims_json)],
            demo_mode=False,
        )
        row.status = RunStatus.RUNNING.value
        row.started_at = _utcnow()
        session.add(row)
        session.commit()

    async def emit(event: RunEvent) -> None:
        _append_event(run_id, event)

    logger.info("Run %s started for case %d", run_id, case_input.case_id)
    try:
        report = await asyncio.wait_for(
            investigate_case(case_input, search_client=search_client, emit_event=emit),
            timeout=settings.RUN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Run %s exceeded %.0fs and was stopped", run_id, settings.RUN_TIMEOUT_SECONDS)
        _finish(
            run_id,
            RunStatus.FAILED,
            None,
            [RunError(code="RUN_TIMEOUT", message="The investigation took too long and was stopped.",
                      step="run", retryable=True)],
            ("run", EventStatus.FAILED, "Investigation stopped: time limit reached"),
        )
        return
    except Exception as exc:  # unexpected investigator failure
        logger.error("Run %s failed: %s", run_id, type(exc).__name__)
        _finish(
            run_id,
            RunStatus.FAILED,
            None,
            [RunError(code="INVESTIGATION_ERROR",
                      message="The investigation could not be completed because of an internal error.",
                      step="run", retryable=True)],
            ("run", EventStatus.FAILED, "Investigation could not be completed"),
        )
        return

    if report.run_id != run_id:
        # The snapshot validator would reject this; record it as a failure instead.
        _finish(run_id, RunStatus.FAILED, None,
                [RunError(code="INVALID_RESULT", message="The investigator returned a result for another run.",
                          step="run", retryable=False)])
        return

    status = RunStatus.PARTIAL if report.errors else RunStatus.COMPLETED
    _finish(run_id, status, report, list(report.errors))
    logger.info("Run %s finished with status %s", run_id, status.value)


def recover_interrupted_runs() -> int:
    """Mark runs left QUEUED/RUNNING by a previous process as FAILED (retryable)."""
    with Session(db_session.engine) as session:
        rows = session.exec(
            select(InvestigationRun).where(InvestigationRun.status.in_(ACTIVE_STATUSES))
        ).all()
        ids = [r.run_id for r in rows]
    for run_id in ids:
        _finish(
            run_id,
            RunStatus.FAILED,
            None,
            [RunError(code="RUN_INTERRUPTED",
                      message="The server restarted before this investigation finished. Run it again.",
                      step="run", retryable=True)],
            ("run", EventStatus.FAILED, "Investigation interrupted by a server restart"),
        )
    if ids:
        logger.warning("Marked %d interrupted run(s) as FAILED", len(ids))
    return len(ids)


def delete_case(session: Session, offer: Offer) -> None:
    """Remove a case and everything derived from it."""
    for row in _case_runs(session, offer.id):
        session.delete(row)
    for ev in session.exec(select(Evidence).where(Evidence.offer_id == offer.id)).all():
        session.delete(ev)
    session.delete(offer)
    session.commit()


def purge_expired_cases(now: Optional[datetime] = None) -> int:
    """Delete cases older than CASE_RETENTION_DAYS. Returns the number removed."""
    cutoff = (now or _utcnow()) - timedelta(days=settings.CASE_RETENTION_DAYS)
    removed = 0
    with Session(db_session.engine) as session:
        offers = session.exec(select(Offer).where(Offer.created_at < cutoff)).all()
        for offer in offers:
            delete_case(session, offer)
            removed += 1
    if removed:
        logger.info("Retention purge removed %d case(s)", removed)
    return removed
