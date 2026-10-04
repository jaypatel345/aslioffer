import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.db.session import init_db, engine
from app.db.models.offer import Offer
from app.db.models.run import InvestigationRun
from app.schemas.contract import InvestigationResult, RunEvent, EventStatus, RunSnapshot
from app.services.runs import run_service

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "contract" / "v1" / "examples"
UNKNOWN_ID = 987654321


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    init_db()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, text="Offer from Acme Ltd for Analyst.", title="Test offer", **extra):
    res = client.post("/offers/upload", data={"title": title, "source_type": "text", "raw_content": text, **extra})
    assert res.status_code == 201, res.text
    body = res.json()
    return body["offer_id"], {"X-Case-Token": body["access_token"]}


def _example_result(name="investigation_result_high_risk_impersonation.json"):
    return json.loads((EXAMPLES / name).read_text())


class FakeInvestigator:
    """Stands in for investigate_case: emits real events and returns a contract result."""

    def __init__(self, example="investigation_result_high_risk_impersonation.json", raises=None):
        self.example = example
        self.raises = raises
        self.calls = []

    async def __call__(self, case_input, search_client=None, emit_event=None, budget=None):
        self.calls.append(case_input)
        await emit_event(RunEvent(run_id=case_input.run_id, sequence=0, step="extract_claims",
                                  status=EventStatus.STARTED, public_message="Extracting offer claims",
                                  timestamp=datetime.now(timezone.utc)))
        if self.raises:
            raise self.raises
        await emit_event(RunEvent(run_id=case_input.run_id, sequence=1, step="extract_claims",
                                  status=EventStatus.COMPLETED, public_message="Extracted claims",
                                  timestamp=datetime.now(timezone.utc)))
        data = _example_result(self.example)
        data["run_id"] = case_input.run_id
        return InvestigationResult.model_validate(data)


@pytest.fixture
def fake():
    inv = FakeInvestigator()
    with patch("app.services.runs.run_service.investigate_case", inv):
        yield inv


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "AsliOffer" in data["service"]


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["project"] == "AsliOffer"


# --- J3: runs, snapshots, polling --------------------------------------------


def test_run_lifecycle_persists_snapshot_and_report(client, fake):
    offer_id, auth = _upload(client)
    res = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth)
    assert res.status_code == 202
    queued = RunSnapshot.model_validate(res.json())
    assert queued.status.value == "QUEUED" and queued.version == 1 and queued.report is None

    # TestClient runs background tasks before returning, so the run is finished.
    polled = RunSnapshot.model_validate(client.get(f"/analysis/runs/{queued.run_id}", headers=auth).json())
    assert polled.status.value == "COMPLETED"
    assert [e.sequence for e in polled.events] == [0, 1]
    assert polled.report.overall_outcome.value == "HIGH_RISK"
    assert polled.started_at and polled.finished_at

    report = client.get(f"/offers/{offer_id}/report", headers=auth)
    assert report.status_code == 200
    assert report.json() == polled.model_dump(mode="json")
    assert len(fake.calls) == 1


def test_report_get_reads_only_and_never_runs(client, fake):
    offer_id, auth = _upload(client)
    with patch("app.services.runs.run_service.execute_run") as execute:
        res = client.get(f"/offers/{offer_id}/report", headers=auth)
    assert res.status_code == 409
    assert "no finished report" in res.json()["detail"]
    execute.assert_not_called()
    assert fake.calls == []

    client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth)
    with patch("app.services.search.serpapi_client.SerpApiClient.search") as search:
        first = client.get(f"/offers/{offer_id}/report", headers=auth).json()
        second = client.get(f"/offers/{offer_id}/report", headers=auth).json()
    assert first == second
    search.assert_not_called()
    assert len(fake.calls) == 1


def test_completed_report_is_reused_without_force_refresh(client, fake):
    offer_id, auth = _upload(client)
    first = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth).json()
    again = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth)
    assert again.status_code == 200
    assert again.json()["run_id"] == first["run_id"]
    assert len(fake.calls) == 1


def test_force_refresh_creates_new_version_and_keeps_previous(client, fake):
    offer_id, auth = _upload(client)
    v1 = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth).json()
    v2 = client.post("/analysis/run", json={"offer_id": offer_id, "force_refresh": True}, headers=auth).json()
    assert v2["version"] == 2 and v2["previous_run_id"] == v1["run_id"]
    runs = client.get(f"/offers/{offer_id}/runs", headers=auth).json()
    assert [r["version"] for r in runs] == [2, 1]
    assert all(r["status"] == "COMPLETED" for r in runs)
    assert client.get(f"/offers/{offer_id}/report", headers=auth).json()["run_id"] == v2["run_id"]
    assert len(fake.calls) == 2


def test_active_run_is_reused_and_does_not_start_another(client, fake):
    offer_id, auth = _upload(client)
    with Session(engine) as s:
        s.add(InvestigationRun(run_id="run_active_test", case_id=offer_id, version=1, status="RUNNING",
                               input_hash="x", started_at=datetime.now(timezone.utc)))
        s.commit()
    for force in (False, True):
        res = client.post("/analysis/run", json={"offer_id": offer_id, "force_refresh": force}, headers=auth)
        assert res.status_code == 200
        assert res.json()["run_id"] == "run_active_test"
        assert res.json()["status"] == "RUNNING"
    assert fake.calls == []


def test_investigator_partial_errors_give_partial_run(client):
    inv = FakeInvestigator("investigation_result_cannot_verify_provider_outage.json")
    with patch("app.services.runs.run_service.investigate_case", inv):
        offer_id, auth = _upload(client)
        run = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth).json()
    snap = client.get(f"/analysis/runs/{run['run_id']}", headers=auth).json()
    assert snap["status"] == "PARTIAL"
    assert snap["errors"] and snap["report"]["errors"] == snap["errors"]
    assert snap["report"]["overall_outcome"] == "CANNOT_VERIFY"


def test_investigator_crash_marks_run_failed_without_fallback(client):
    inv = FakeInvestigator(raises=RuntimeError("boom"))
    with patch("app.services.runs.run_service.investigate_case", inv):
        offer_id, auth = _upload(client)
        run = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth).json()
    snap = client.get(f"/analysis/runs/{run['run_id']}", headers=auth).json()
    assert snap["status"] == "FAILED"
    assert snap["report"] is None
    assert snap["errors"][0]["code"] == "INVESTIGATION_ERROR"
    assert "boom" not in json.dumps(snap)
    assert snap["events"][-1]["status"] == "FAILED"
    # No report exists, so the report endpoint still says so instead of inventing one.
    assert client.get(f"/offers/{offer_id}/report", headers=auth).status_code == 409


def test_restart_marks_unfinished_runs_failed(client):
    offer_id, auth = _upload(client)
    with Session(engine) as s:
        s.add(InvestigationRun(run_id="run_interrupted_test", case_id=offer_id, version=1,
                               status="RUNNING", input_hash="x"))
        s.commit()
    run_service.recover_interrupted_runs()
    snap = client.get("/analysis/runs/run_interrupted_test", headers=auth).json()
    assert snap["status"] == "FAILED"
    assert snap["errors"][0]["code"] == "RUN_INTERRUPTED"
    assert snap["errors"][0]["retryable"] is True


def test_completed_report_survives_new_app_instance(client, fake):
    offer_id, auth = _upload(client)
    client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth)
    with TestClient(app) as restarted:  # lifespan runs recovery again
        res = restarted.get(f"/offers/{offer_id}/report", headers=auth)
    assert res.status_code == 200 and res.json()["status"] == "COMPLETED"


def test_real_pipeline_without_search_key_is_honest_partial(client):
    """End to end through the real investigator with no SerpApi key configured."""
    text = (
        "Congratulations from Tata Consultancy Services. Pay refundable security deposit "
        "of INR 15,000 via UPI to tcs-recruiter@upi. Contact HR at rohit.tcs@gmail.com."
    )
    offer_id, auth = _upload(client, text=text)
    run = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth).json()
    snap = RunSnapshot.model_validate(client.get(f"/analysis/runs/{run['run_id']}", headers=auth).json())
    assert snap.status.value in ("COMPLETED", "PARTIAL")
    assert snap.report.demo_mode is False
    assert all(e.retrieval_status.value != "DEMO" for e in snap.report.evidence)
    # An explicit fee demand is a grounded local signal even when search is down.
    assert snap.report.overall_outcome.value == "HIGH_RISK"
    assert snap.events, "progress must come from real investigator events"


# --- J4: claim preview and confirmation --------------------------------------


def test_claim_preview_is_local_and_grounded(client):
    text = "Infosys Limited offers you the role of Systems Engineer. Contact pooja@infosys.com."
    offer_id, auth = _upload(client, text=text)
    with patch("app.services.search.serpapi_client.SerpApiClient.search") as search:
        res = client.get(f"/offers/{offer_id}/claims", headers=auth)
    search.assert_not_called()
    assert res.status_code == 200
    body = res.json()
    employer = next(c for c in body["claims"] if c["kind"] == "employer")
    assert "Infosys" in employer["value"]
    if employer["source_quote"]:
        assert employer["source_quote"] in body["text"]


def test_confirmed_claims_reach_the_investigator(client, fake):
    offer_id, auth = _upload(client, text="Offer for Analyst role. Contact hr@acme.example.")
    claims = client.get(f"/offers/{offer_id}/claims", headers=auth).json()["claims"]
    employer = next(c for c in claims if c["kind"] == "employer")
    confirmed = [{"claim_id": employer["claim_id"], "kind": "employer", "value": "Acme Ltd",
                  "extraction_status": "USER_EDITED"}]
    res = client.post("/analysis/run", json={"offer_id": offer_id, "confirmed_claims": confirmed}, headers=auth)
    assert res.status_code == 202
    assert fake.calls[0].confirmed_claims[0].value == "Acme Ltd"

    # Different confirmations are different inputs: the earlier report is not reused.
    res2 = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth)
    assert res2.status_code == 202 and len(fake.calls) == 2


def test_invalid_confirmation_is_rejected_before_any_run(client, fake):
    offer_id, auth = _upload(client)
    bad = [{"claim_id": "c99", "kind": "employer", "value": "X", "extraction_status": "USER_EDITED"}]
    res = client.post("/analysis/run", json={"offer_id": offer_id, "confirmed_claims": bad}, headers=auth)
    assert res.status_code == 422
    assert fake.calls == []


def test_redaction_strips_candidate_identifiers_before_investigation(client, fake):
    text = ("Acme Ltd offer. Aadhaar 1234 5678 9012, PAN ABCDE1234F, account no 123456789012345. "
            "Your OTP is 482913. Recruiter: hr@acme.example, +919876543210.")
    offer_id, auth = _upload(client, text=text)
    client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth)
    sent = fake.calls[0].redacted_text
    for secret in ("1234 5678 9012", "ABCDE1234F", "123456789012345", "482913"):
        assert secret not in sent
    assert "hr@acme.example" in sent and "+919876543210" in sent


# --- J2: unknown IDs are 404s, never a fabricated case ------------------------


@pytest.mark.parametrize("prefix", ["", "/api/v1"])
def test_unknown_offer_is_404(client, prefix):
    res = client.get(f"{prefix}/offers/{UNKNOWN_ID}", headers={"X-Case-Token": "x"})
    assert res.status_code == 404
    assert res.json() == {"detail": f"Offer {UNKNOWN_ID} not found."}


@pytest.mark.parametrize("prefix", ["", "/api/v1"])
def test_unknown_offer_report_is_404_and_runs_nothing(client, prefix, fake):
    with patch("app.services.search.serpapi_client.SerpApiClient.search") as search:
        res = client.get(f"{prefix}/offers/{UNKNOWN_ID}/report")
    assert res.status_code == 404
    assert "TCS" not in res.text and "Tata" not in res.text
    search.assert_not_called()
    assert fake.calls == []


def test_unknown_offer_analysis_run_is_404(client, fake):
    res = client.post("/analysis/run", json={"offer_id": UNKNOWN_ID, "force_refresh": False})
    assert res.status_code == 404
    assert res.json()["detail"] == f"Offer {UNKNOWN_ID} not found."
    assert fake.calls == []


def test_unknown_run_is_404(client):
    assert client.get("/analysis/runs/run_does_not_exist").status_code == 404


def test_existing_offer_is_returned_unchanged(client):
    offer_id, auth = _upload(client, text="Offer from Acme Ltd.", title="Lookup test")
    res = client.get(f"/offers/{offer_id}", headers=auth)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == offer_id
    assert body["title"] == "Lookup test"
    assert body["raw_content"] == "Offer from Acme Ltd."


def test_preset_upload_is_labelled_as_sample(client):
    payload = {"title": "Coorix Internship", "source_type": "text", "raw_content": "Sample text.", "sample": "true"}
    res = client.post("/offers/upload", data=payload)
    assert res.status_code == 201
    assert res.json()["title"] == "Sample: Coorix Internship"


def test_user_upload_is_not_labelled_as_sample(client):
    payload = {"title": "My offer", "source_type": "text", "raw_content": "Real text."}
    assert client.post("/offers/upload", data=payload).json()["title"] == "My offer"


# --- J6: access, limits, deletion, retention ---------------------------------


def test_case_requires_its_own_token(client, fake):
    offer_id, auth = _upload(client)
    other_id, other_auth = _upload(client)
    for headers in ({}, {"X-Case-Token": "wrong"}, other_auth):
        assert client.get(f"/offers/{offer_id}", headers=headers).status_code == 404
        assert client.get(f"/offers/{offer_id}/claims", headers=headers).status_code == 404
        assert client.get(f"/offers/{offer_id}/report", headers=headers).status_code == 404
        assert client.post("/analysis/run", json={"offer_id": offer_id}, headers=headers).status_code == 404
    run = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth).json()
    assert client.get(f"/analysis/runs/{run['run_id']}", headers=other_auth).status_code == 404
    with Session(engine) as s:
        stored = s.get(Offer, offer_id).access_token_hash
    assert stored and auth["X-Case-Token"] not in stored


def test_upload_rejects_unsupported_file_type(client):
    res = client.post("/offers/upload", files={"file": ("offer.exe", b"MZ...", "application/octet-stream")})
    assert res.status_code == 415


def test_upload_rejects_oversized_file(client):
    from app.core.config import settings
    big = b"%PDF-1.4" + b"0" * settings.MAX_UPLOAD_BYTES
    res = client.post("/offers/upload", files={"file": ("offer.pdf", big, "application/pdf")})
    assert res.status_code == 413


def test_upload_rejects_oversized_text(client):
    from app.core.config import settings
    res = client.post("/offers/upload", data={"raw_content": "a" * (settings.MAX_TEXT_CHARS + 1)})
    assert res.status_code == 413


def test_upload_requires_content(client):
    assert client.post("/offers/upload", data={"title": "x"}).status_code == 400


def test_delete_removes_case_and_runs(client, fake):
    offer_id, auth = _upload(client)
    run = client.post("/analysis/run", json={"offer_id": offer_id}, headers=auth).json()
    assert client.delete(f"/offers/{offer_id}", headers={"X-Case-Token": "wrong"}).status_code == 404
    assert client.delete(f"/offers/{offer_id}", headers=auth).status_code == 204
    assert client.get(f"/offers/{offer_id}", headers=auth).status_code == 404
    with Session(engine) as s:
        assert s.get(InvestigationRun, run["run_id"]) is None


def test_retention_purges_old_cases_only(client, fake):
    old_id, old_auth = _upload(client)
    new_id, new_auth = _upload(client)
    client.post("/analysis/run", json={"offer_id": old_id}, headers=old_auth)
    with Session(engine) as s:
        old = s.get(Offer, old_id)
        old.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        s.add(old)
        s.commit()
    assert run_service.purge_expired_cases() >= 1
    assert client.get(f"/offers/{old_id}", headers=old_auth).status_code == 404
    assert client.get(f"/offers/{new_id}", headers=new_auth).status_code == 200


def test_logs_are_scrubbed_of_contacts():
    import logging
    from app.core.logging import logger, ScrubbingFilter

    record = logging.LogRecord("aslioffer", logging.INFO, __file__, 1,
                               "contact %s or %s api_key=%s", ("a.b@gmail.com", "+91 98765 43210", "SECRET"), None)
    ScrubbingFilter().filter(record)
    msg = record.getMessage()
    assert "a.b@gmail.com" not in msg and "98765" not in msg and "SECRET" not in msg
