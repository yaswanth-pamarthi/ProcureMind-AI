import json
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
import pytest
from app.core import ROOT, Session
from app.models import RFQ, Submission, Vendor, Finding, Chunk


def test_labelled_quotation_accuracy():
    labels = json.loads((ROOT / "sample-data" / "expected-extractions.json").read_text())
    correct = total = 0
    with Session() as db:
        rfq = db.scalar(select(RFQ).where(RFQ.number == "RFQ-DEMO-100"))
        for expected in labels:
            vendor = db.scalar(select(Vendor).where(Vendor.name == expected["vendor"]))
            submission = db.scalar(
                select(Submission).where(Submission.rfq_id == rfq.id, Submission.vendor_id == vendor.id)
            )
            for field, value in expected.items():
                if field == "vendor":
                    continue
                total += 1
                correct += submission.extracted_json[field] == value
    assert correct / total == 1


def test_contract_findings_have_exact_valid_excerpts():
    with Session() as db:
        findings = db.scalars(select(Finding)).all()
        assert findings
        for finding in findings:
            chunk = db.get(Chunk, finding.evidence_chunk_id)
            e = finding.payload_json["evidence"]
            assert chunk.document_id == finding.document_id == e["document_id"]
            assert e["page"] == chunk.page_start and e["excerpt"] in chunk.text


@pytest.mark.parametrize("table", ["activity_logs", "approvals", "agent_outputs", "vendor_scores"])
def test_audit_history_is_append_only(table):
    with Session() as db:
        id = db.scalar(text(f"SELECT id FROM {table} LIMIT 1"))
        if not id:
            pytest.skip("Execute demonstration first")
        with pytest.raises(DBAPIError):
            db.execute(text(f"UPDATE {table} SET id=id WHERE id=:id"), {"id": id})
        db.rollback()
