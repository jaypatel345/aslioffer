import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import init_db


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    init_db()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "AsliOffer" in data["service"]


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["project"] == "AsliOffer"


def test_upload_and_report_scam_flow(client):
    scam_payload = {
        "title": "TCS Scam Test",
        "source_type": "text",
        "raw_content": (
            "Congratulations from Tata Consultancy Services. Pay refundable security deposit "
            "of INR 15,000 via UPI to tcs-recruiter@upi. Contact HR at rohit.tcs@gmail.com."
        ),
    }
    upload_res = client.post("/offers/upload", data=scam_payload)
    assert upload_res.status_code == 201
    offer_id = upload_res.json()["offer_id"]

    report_res = client.get(f"/offers/{offer_id}/report")
    assert report_res.status_code == 200
    report = report_res.json()
    assert report["offer_id"] == offer_id
    assert report["risk_level"] == "HIGH_RISK"
    assert report["risk_score"] >= 0.50
    assert len(report["red_flags"]) > 0
    assert len(report["findings"]) == 4


def test_upload_and_report_verified_flow(client):
    legit_payload = {
        "title": "Infosys Specialist Offer",
        "source_type": "text",
        "raw_content": (
            "Infosys Limited is pleased to offer you the role of Systems Engineer Specialist. "
            "CTC: INR 6,25,000 per annum. Contact pooja.kulkarni@infosys.com. Infosys never demands any fees."
        ),
    }
    upload_res = client.post("/offers/upload", data=legit_payload)
    assert upload_res.status_code == 201
    offer_id = upload_res.json()["offer_id"]

    report_res = client.get(f"/offers/{offer_id}/report")
    assert report_res.status_code == 200
    report = report_res.json()
    assert report["offer_id"] == offer_id
    assert report["risk_level"] == "VERIFIED"
    assert report["risk_score"] < 0.25
    assert len(report["green_flags"]) > 0


def test_analysis_run_endpoint(client):
    request_payload = {"offer_id": 101, "force_refresh": False}
    analysis_res = client.post("/analysis/run", json=request_payload)
    assert analysis_res.status_code == 200
    data = analysis_res.json()
    assert "risk_level" in data
    assert "findings" in data
