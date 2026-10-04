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
    from unittest.mock import patch
    from app.services.search.serpapi_client import SearchResult, SearchOutcome

    legit_payload = {
        "title": "Infosys Specialist Offer",
        "source_type": "text",
        "raw_content": (
            "Infosys Limited is pleased to offer you the role of Systems Engineer Specialist. "
            "CTC: INR 6,25,000 per annum. Contact pooja.kulkarni@infosys.com. Infosys never demands any fees."
        ),
    }

    mock_search_res = SearchResult(
        query="Infosys",
        provider="serpapi",
        outcome=SearchOutcome.SUCCESS,
        results=[
            {
                "title": "Infosys - Official Careers",
                "link": "https://www.infosys.com/careers",
                "snippet": "Infosys official careers page. We never demand fees from candidates.",
            },
            {
                "title": "Infosys Recruitment Lead - Pooja Kulkarni",
                "link": "https://www.infosys.com/careers/pooja-kulkarni",
                "snippet": "Pooja Kulkarni - Specialist Recruitment Lead at Infosys Limited. Contact: pooja.kulkarni@infosys.com",
            },
        ],
        knowledge_graph={
            "title": "Infosys Limited",
            "website": "https://www.infosys.com",
            "careers_url": "https://www.infosys.com/careers",
        },
    )

    with patch("app.services.search.serpapi_client.SerpApiClient.search", return_value=mock_search_res):
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
    upload_res = client.post(
        "/offers/upload",
        data={"title": "Run endpoint test", "source_type": "text", "raw_content": "Offer from Acme Ltd for Analyst."},
    )
    offer_id = upload_res.json()["offer_id"]
    analysis_res = client.post("/analysis/run", json={"offer_id": offer_id, "force_refresh": False})
    assert analysis_res.status_code == 200
    data = analysis_res.json()
    assert data["offer_id"] == offer_id
    assert "risk_level" in data
    assert "findings" in data


# --- J2: unknown IDs are 404s, never a fabricated TCS/Infosys case -------------

UNKNOWN_ID = 987654321


@pytest.mark.parametrize("prefix", ["", "/api/v1"])
def test_unknown_offer_is_404(client, prefix):
    res = client.get(f"{prefix}/offers/{UNKNOWN_ID}")
    assert res.status_code == 404
    assert res.json() == {"detail": f"Offer {UNKNOWN_ID} not found."}


@pytest.mark.parametrize("prefix", ["", "/api/v1"])
def test_unknown_offer_report_is_404_and_runs_nothing(client, prefix):
    from unittest.mock import patch

    with patch("app.services.search.serpapi_client.SerpApiClient.search") as search, patch(
        "app.api.v1.routers.offers.extractor.extract_entities"
    ) as extract:
        res = client.get(f"{prefix}/offers/{UNKNOWN_ID}/report")
    assert res.status_code == 404
    assert "TCS" not in res.text and "Tata" not in res.text
    search.assert_not_called()
    extract.assert_not_called()


@pytest.mark.parametrize("legacy_demo_id", [101, 102])
def test_former_demo_ids_are_not_special(client, legacy_demo_id):
    # 101/102 used to return built-in TCS/Infosys reports. They are ordinary IDs now.
    from app.db.session import engine
    from sqlmodel import Session
    from app.db.models.offer import Offer

    with Session(engine) as s:
        if s.get(Offer, legacy_demo_id) is not None:
            pytest.skip("local database happens to contain this ID")
    assert client.get(f"/offers/{legacy_demo_id}/report").status_code == 404
    assert client.post("/analysis/run", json={"offer_id": legacy_demo_id}).status_code == 404


def test_unknown_offer_analysis_run_is_404(client):
    res = client.post("/analysis/run", json={"offer_id": UNKNOWN_ID, "force_refresh": False})
    assert res.status_code == 404
    assert res.json()["detail"] == f"Offer {UNKNOWN_ID} not found."


def test_existing_offer_is_returned_unchanged(client):
    payload = {"title": "Lookup test", "source_type": "text", "raw_content": "Offer from Acme Ltd."}
    offer_id = client.post("/offers/upload", data=payload).json()["offer_id"]
    res = client.get(f"/offers/{offer_id}")
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
