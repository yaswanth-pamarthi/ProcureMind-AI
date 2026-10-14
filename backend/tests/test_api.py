import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.core import Session, settings
from app.models import RFQ, Document, Submission


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(c, role):
    response = c.post("/auth/login", json={"email": role + "@local.demo", "password": settings.demo_password})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_authentication_required(client):
    assert client.get("/rfqs").status_code == 401


def test_bad_password(client):
    assert (
        client.post("/auth/login", json={"email": "analyst@local.demo", "password": "wrong"}).status_code
        == 401
    )


def test_analyst_cannot_finalize(client):
    assert (
        client.post(
            "/recommendations/not-real/decision",
            headers=login(client, "analyst"),
            json={"decision": "approve", "reason": "Reviewed all evidence"},
        ).status_code
        == 403
    )


def test_analyst_cannot_generate_final_report(client):
    assert client.post("/rfqs/not-real/reports", headers=login(client, "analyst")).status_code == 403


def test_manager_cannot_run_analyst_workflow(client):
    assert client.post("/rfqs/not-real/analysis-runs", headers=login(client, "manager")).status_code == 403


def test_missing_object_is_404(client):
    assert client.get("/rfqs/not-real", headers=login(client, "manager")).status_code == 404


def test_contract_page_never_displays_another_documents_quotation(client):
    with Session() as db:
        doc = db.scalar(
            select(Document).where(Document.type == "contract", Document.parse_status == "PROCESSED")
        )
    if not doc:
        pytest.skip("Seed contract PDFs first")
    response = client.get("/documents/" + doc.id + "/findings", headers=login(client, "manager"))
    assert response.status_code == 200 and response.json()["quotation"] == {}


def test_blank_decision_reason_rejected():
    from app.schemas import DecisionIn
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DecisionIn(decision="approve", reason="       ")


def test_analyst_object_ownership(client):
    from app.core import current_user, User

    with Session() as db:
        rfq = db.scalar(select(RFQ).where(RFQ.number == "RFQ-DEMO-100"))
    if not rfq:
        pytest.skip("Seed data not installed")
    app.dependency_overrides[current_user] = lambda: User(
        id="unrelated-user", role="analyst", email="unrelated@local.demo", password_hash="unused"
    )
    try:
        assert client.get("/rfqs/" + rfq.id).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_seed_document_evidence_valid():
    with Session() as db:
        rfq = db.scalar(select(RFQ).where(RFQ.number == "RFQ-DEMO-100"))
        if not rfq:
            pytest.skip("Seed data not installed")
        submissions = db.scalars(select(Submission).where(Submission.rfq_id == rfq.id)).all()
        assert len(submissions) == 3
        for s in submissions:
            assert s.extracted_json["evidence"]
            for evidence in s.extracted_json["evidence"].values():
                from app.models import Chunk

                chunk = db.get(Chunk, evidence["chunk_id"])
                doc = db.get(Document, evidence["document_id"])
                assert (
                    chunk.document_id == doc.id
                    and doc.submission_id == s.id
                    and chunk.page_start == evidence["page"]
                )
