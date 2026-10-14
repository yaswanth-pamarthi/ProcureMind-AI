import pytest
from pydantic import ValidationError
from fastapi import HTTPException
from app.schemas import RFQIn, Quotation, DEFAULT_WEIGHTS
from app.scoring import score_vendors
from app.scoring import risk_level


@pytest.mark.parametrize(
    "likelihood,impact,expected",
    [
        ("low", "low", "low"),
        ("low", "medium", "low"),
        ("low", "high", "medium"),
        ("medium", "low", "low"),
        ("medium", "medium", "medium"),
        ("medium", "high", "high"),
        ("high", "low", "medium"),
        ("high", "medium", "high"),
        ("high", "high", "critical"),
    ],
)
def test_documented_risk_matrix(likelihood, impact, expected):
    assert risk_level(likelihood, impact) == expected


from app.documents import validate_pdf, section_chunks


def row(name, price, days, quality=90, compliance="compliant", mandatory=False, penalty=0):
    return {
        "vendor_id": name,
        "total": price,
        "delivery_days": days,
        "quality": quality,
        "currency": "INR",
        "compliance": compliance,
        "mandatory_failure": mandatory,
        "penalty": penalty,
    }


def test_reproducible_weighted_score():
    rows = [row("Alpha", 100, 10), row("Beta", 80, 20, 80, penalty=30)]
    a = score_vendors(rows, DEFAULT_WEIGHTS)
    b = score_vendors(rows, DEFAULT_WEIGHTS)
    assert a == b
    alpha = next(r for r in a if r["vendor_id"] == "Alpha")
    assert alpha["score"] == 92.0
    assert sum(f["contribution"] for f in alpha["breakdown"]) == 92


def test_mandatory_failure_excluded_even_when_cheapest():
    scores = score_vendors(
        [row("failed", 1, 1, 100, mandatory=True), row("eligible", 100, 10)], DEFAULT_WEIGHTS
    )
    assert scores[0]["vendor_id"] == "eligible" and scores[0]["score"] == 98
    assert not scores[1]["eligible"]


@pytest.mark.parametrize("field,value", [("total", 0), ("delivery_days", 0), ("quality", None)])
def test_missing_invalid_inputs_stop(field, value):
    bad = row("bad", 100, 10)
    bad[field] = value
    with pytest.raises(ValueError):
        score_vendors([bad, row("valid", 100, 10)], DEFAULT_WEIGHTS)


def test_mixed_currencies_stop():
    bad = row("USD", 100, 10)
    bad["currency"] = "USD"
    with pytest.raises(ValueError):
        score_vendors([bad, row("INR", 100, 10)], DEFAULT_WEIGHTS)


def test_all_ineligible_stops():
    with pytest.raises(ValueError):
        score_vendors([row("bad", 100, 10, compliance="failed")], DEFAULT_WEIGHTS)


def test_weight_sum_guard():
    with pytest.raises(ValueError):
        score_vendors([row("a", 100, 10)], {**DEFAULT_WEIGHTS, "price": 31})


def test_rfq_schema_rejects_wrong_weights():
    with pytest.raises(ValidationError):
        RFQIn(
            number="RFQ-1",
            title="Test laptops",
            budget=100,
            currency="INR",
            due_date="2026-12-01",
            items=[{"description": "Laptop", "quantity": 1, "target_price": 100}],
            weights_json={**DEFAULT_WEIGHTS, "price": 90},
        )


def test_quotation_arithmetic():
    data = dict(
        currency="INR",
        unit_price=100,
        quantity=10,
        tax=18,
        total=1180,
        delivery_days=2,
        payment="net30",
        warranty_months=12,
        evidence={},
    )
    assert Quotation(**data).total == 1180
    with pytest.raises(ValidationError):
        Quotation(**{**data, "total": 900})


@pytest.mark.parametrize(
    "name,mime,data",
    [
        ("evil.exe", "application/pdf", b"%PDF-fake"),
        ("file.pdf", "text/html", b"%PDF-fake"),
        ("file.pdf", "application/pdf", b"not pdf"),
    ],
)
def test_upload_rejects_spoofed_files(name, mime, data):
    with pytest.raises(HTTPException):
        validate_pdf(name, mime, data)


def test_chunking_preserves_bounded_overlap():
    words = [f"word{i}" for i in range(1500)]
    chunks = section_chunks(" ".join(words))
    assert all(len(c.split()) <= 650 for c in chunks)
    assert set(words) == set(" ".join(chunks).split())
    assert chunks[0].split()[-80:] == chunks[1].split()[:80]
