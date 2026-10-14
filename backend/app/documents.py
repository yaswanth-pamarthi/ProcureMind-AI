import hashlib, io, re, time
from pypdf import PdfReader
from sqlalchemy import select, delete
from fastapi import HTTPException
from .core import ROOT, uid
from .models import Document, Chunk, Finding, Submission, Item, QuotationItem
from .schemas import Quotation
from .ai import embed

MAX_UPLOAD = 10 * 1024 * 1024


def validate_pdf(name, content_type, data):
    if (
        not name.lower().endswith(".pdf")
        or content_type not in ("application/pdf", "application/octet-stream")
        or not data.startswith(b"%PDF-")
    ):
        raise HTTPException(415, "Only valid PDF documents are accepted")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Maximum upload is 10 MB")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF")
        if len(reader.pages) > 100:
            raise ValueError("Maximum 100 pages")
    except Exception as e:
        raise HTTPException(422, "Unreadable or unsupported PDF") from e


def upload(db, submission, kind, name, data):
    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(Document).where(
            Document.submission_id == submission.id, Document.hash == digest, Document.type == kind
        )
    )
    if existing:
        return existing
    directory = ROOT / "storage" / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    id = uid()
    path = directory / (id + ".pdf")
    path.write_bytes(data)
    document = Document(
        id=id, submission_id=submission.id, type=kind, original_name=name, path=str(path), hash=digest
    )
    db.add(document)
    db.flush()
    return document


def section_chunks(text, max_words=650, overlap=80):
    # Preserve clauses/paragraphs; long paragraphs get a bounded overlapping split.
    blocks = re.split(r"\n\s*\n|(?=\n(?:\d+[.)]|[A-Z][A-Za-z ]{2,35}:))", text)
    output = []
    current = []
    count = 0
    for block in blocks:
        words = block.split()
        if not words:
            continue
        if len(words) > max_words:
            if current:
                output.append("\n".join(current))
                current = []
                count = 0
            for start in range(0, len(words), max_words - overlap):
                output.append(" ".join(words[start : start + max_words]))
        else:
            if count + len(words) > max_words and current:
                output.append("\n".join(current))
                current = [" ".join(" ".join(current).split()[-overlap:])]
                count = overlap
            current.append(block.strip())
            count += len(words)
    if current:
        output.append("\n".join(current))
    return output


def process(db, document):
    if document.parse_status == "PROCESSED":
        return document
    start = time.perf_counter()
    reader = PdfReader(document.path)
    pages = [(i + 1, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages)]
    empty = [page for page, text in pages if len(text) < 20]
    if empty:
        document.parse_status = "OCR_REQUIRED"
        document.metrics_json = {"ocr_required_pages": empty}
        db.commit()
        return document
    pieces = [(page, chunk) for page, text in pages for chunk in section_chunks(text)]
    vectors = embed([chunk for _, chunk in pieces])
    db.execute(delete(Finding).where(Finding.document_id == document.id))
    db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    chunks = []
    for (page, text), vector in zip(pieces, vectors):
        chunk = Chunk(
            id=uid(),
            document_id=document.id,
            page_start=page,
            page_end=page,
            section=text.splitlines()[0][:100],
            text=text,
            text_hash=hashlib.sha256(text.encode()).hexdigest(),
            embedding=vector,
        )
        db.add(chunk)
        chunks.append(chunk)
    db.flush()
    if document.type == "quotation":
        text = "\n".join(c.text for c in chunks)
        patterns = {
            "currency": r"Currency\s*:\s*([A-Z]{3})",
            "total": r"Total\s*:\s*([\d,.]+)",
            "unit_price": r"Unit price\s*:\s*([\d,.]+)",
            "quantity": r"Quantity\s*:\s*(\d+)",
            "tax": r"Tax\s*:\s*([\d.]+)",
            "delivery_days": r"Delivery days\s*:\s*(\d+)",
            "payment": r"Payment\s*:\s*([^\n]+)",
            "warranty_months": r"Warranty months\s*:\s*(\d+)",
        }
        values = {}
        evidence = {}
        for field, pattern in patterns.items():
            for c in chunks:
                match = re.search(pattern, c.text, re.I)
                if match:
                    values[field] = (
                        match.group(1).replace(",", "")
                        if field not in ("payment", "currency")
                        else match.group(1).strip()
                    )
                    evidence[field] = {
                        "document_id": document.id,
                        "page": c.page_start,
                        "chunk_id": c.id,
                        "excerpt": match.group(0),
                    }
                    break
        try:
            quotation = Quotation(**values, evidence=evidence).model_dump()
        except ValueError as exc:
            document.parse_status = "NEEDS_REVIEW"
            document.metrics_json = {"validation_error": str(exc), "extracted_fields": values}
            db.commit()
            return document
        submission = db.get(Submission, document.submission_id)
        items = db.scalars(select(Item).where(Item.rfq_id == submission.rfq_id)).all()
        if len(items) != 1 or items[0].quantity != quotation["quantity"]:
            document.parse_status = "NEEDS_REVIEW"
            document.metrics_json = {
                "validation_error": "Prepared extractor supports one reconciled line item; quantities must match RFQ"
            }
            db.commit()
            return document
        submission.extracted_json = quotation
        submission.total = quotation["total"]
        submission.currency = quotation["currency"]
        submission.status = "PROCESSED"
        db.execute(delete(QuotationItem).where(QuotationItem.submission_id == submission.id))
        db.add(
            QuotationItem(
                submission_id=submission.id,
                rfq_item_id=items[0].id,
                unit_price=quotation["unit_price"],
                tax=quotation["tax"],
                delivery_days=quotation["delivery_days"],
            )
        )
    else:
        for c in chunks:
            clauses = [
                (
                    "termination",
                    r"terminat\w*[^.\n]*(?:7|seven)\s*days?",
                    "high",
                    "Short unilateral termination notice threatens delivery continuity.",
                    30,
                ),
                (
                    "liability",
                    r"(?:unlimited liability|liability[^.\n]*excluded)",
                    "high",
                    "Unbalanced liability allocation requires manager review.",
                    25,
                ),
                (
                    "payment",
                    r"(?:100%|full)\s*(?:advance|prepayment)",
                    "medium",
                    "Full advance payment exposes buyer to non-delivery risk.",
                    15,
                ),
                (
                    "data_protection",
                    r"data protection[^.\n]*not included",
                    "high",
                    "Contract explicitly excludes data protection commitments.",
                    20,
                ),
            ]
            for category, pattern, severity, finding, penalty in clauses:
                match = re.search(pattern, c.text, re.I)
                if match:
                    payload = {
                        "business_impact": finding,
                        "recommended_action": "Negotiate protective terms before award.",
                        "confidence": "high",
                        "penalty": penalty,
                        "evidence": {
                            "document_id": document.id,
                            "page": c.page_start,
                            "chunk_id": c.id,
                            "excerpt": match.group(0),
                        },
                    }
                    db.add(
                        Finding(
                            document_id=document.id,
                            evidence_chunk_id=c.id,
                            category=category,
                            severity=severity,
                            finding=finding,
                            payload_json=payload,
                        )
                    )
    document.parse_status = "PROCESSED"
    document.metrics_json = {
        "pages": len(pages),
        "chunks": len(chunks),
        "characters": sum(len(t) for _, t in pages),
        "duration_seconds": round(time.perf_counter() - start, 3),
        "extractor": "validated-label-parser-v1",
        "embedding_model": "nomic-embed-text",
    }
    if document.type == "quotation":
        document.metrics_json = {**document.metrics_json, "quotation": quotation}
    db.commit()
    return document


def retrieve(db, rfq_id, query, vendor_id=None, kind=None):
    vector = embed([query])[0]
    distance = Chunk.embedding.cosine_distance(vector)
    statement = (
        select(Chunk, distance.label("distance"))
        .join(Document)
        .join(Submission)
        .where(Submission.rfq_id == rfq_id)
    )
    if vendor_id:
        statement = statement.where(Submission.vendor_id == vendor_id)
    if kind:
        statement = statement.where(Document.type == kind)
    rows = db.execute(statement.order_by(distance).limit(6)).all()
    return [
        {
            "chunk_id": c.id,
            "document_id": c.document_id,
            "page": c.page_start,
            "section": c.section,
            "text": c.text,
            "distance": float(d),
        }
        for c, d in rows
    ]
