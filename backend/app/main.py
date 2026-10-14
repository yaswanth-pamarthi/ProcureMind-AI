from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select, text, delete
from sqlalchemy.exc import IntegrityError
from .core import (
    Session,
    session,
    current_user,
    roles,
    login,
    seed_users,
    settings,
    get,
    dump,
    owned,
    audit,
    ROOT,
    User,
    password_hasher,
)
from .models import (
    RFQ,
    Submission,
    Document,
    Vendor,
    Performance,
    Item,
    Run,
    Output,
    Recommendation,
    Finding,
    Chunk,
    Report,
    Approval,
)
from .schemas import Login, Register, VendorIn, PerformanceIn, RFQIn, StatusIn, SubmissionIn, DecisionIn
from .documents import upload, process, retrieve, validate_pdf, MAX_UPLOAD
from .workflows import execute
from .reports import make_report


@asynccontextmanager
async def lifespan(app):
    with Session() as db:
        seed_users(db, ["analyst", "manager"])
    yield


app = FastAPI(title="ProcureMind AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)
editor = roles("analyst", "manager")
analyst = roles("analyst")
manager = roles("manager")


def rfq_access(db, id, user):
    rfq = get(db, RFQ, id)
    owned(rfq, user)
    return rfq


def sub_access(db, id, user):
    sub = get(db, Submission, id)
    rfq_access(db, sub.rfq_id, user)
    return sub


def doc_access(db, id, user):
    doc = get(db, Document, id)
    sub_access(db, doc.submission_id, user)
    return doc


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Record already exists or conflicts with a reference")


@app.get("/health")
def health(db=Depends(session)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "postgresql",
        "ai_mode": settings.ai_mode,
        "model": settings.ollama_chat_model,
    }


@app.post("/auth/login")
def authenticate(body: Login, db=Depends(session)):
    return login(db, body.email, body.password)


@app.post("/auth/register")
def register(body: Register, db=Depends(session)):
    if len(body.password) < 12:
        raise HTTPException(422, "Password must have at least 12 characters")
    user = User(email=body.email, password_hash=password_hasher.hash(body.password), role="analyst")
    db.add(user)
    commit(db)
    return {"email": user.email, "role": user.role}


@app.get("/vendors")
def vendors(user=Depends(current_user), db=Depends(session)):
    return [dump(v) for v in db.scalars(select(Vendor))]


@app.post("/vendors")
def create_vendor(body: VendorIn, user=Depends(editor), db=Depends(session)):
    vendor = Vendor(**body.model_dump())
    db.add(vendor)
    db.flush()
    audit(db, user, "CREATE_VENDOR", vendor.id)
    commit(db)
    return dump(vendor)


@app.post("/vendors/{id}/performance")
def performance(id: str, body: PerformanceIn, user=Depends(editor), db=Depends(session)):
    get(db, Vendor, id)
    p = Performance(vendor_id=id, **body.model_dump())
    db.add(p)
    audit(db, user, "ADD_PERFORMANCE", id)
    commit(db)
    return dump(p)


@app.patch("/vendors/{id}")
def update_vendor(id: str, body: VendorIn, user=Depends(manager), db=Depends(session)):
    v = get(db, Vendor, id)
    for k, value in body.model_dump().items():
        setattr(v, k, value)
    audit(db, user, "UPDATE_VENDOR", id)
    commit(db)
    return dump(v)


@app.get("/vendors/{id}/performance")
def history(id: str, user=Depends(current_user), db=Depends(session)):
    get(db, Vendor, id)
    return [dump(p) for p in db.scalars(select(Performance).where(Performance.vendor_id == id))]


@app.get("/rfqs")
def rfqs(user=Depends(current_user), db=Depends(session)):
    query = select(RFQ).order_by(RFQ.created_at.desc())
    if user.role != "manager":
        query = query.where(RFQ.owner_id == user.id)
    return [dump(r) for r in db.scalars(query)]


@app.post("/rfqs")
def create_rfq(body: RFQIn, user=Depends(editor), db=Depends(session)):
    data = body.model_dump(exclude={"items"})
    data["due_date"] = str(data["due_date"])
    rfq = RFQ(owner_id=user.id, **data)
    db.add(rfq)
    db.flush()
    for item in body.items:
        db.add(Item(rfq_id=rfq.id, **item.model_dump()))
    audit(db, user, "CREATE_RFQ", rfq.id)
    commit(db)
    return dump(rfq)


@app.get("/rfqs/{id}")
def rfq_detail(id: str, user=Depends(current_user), db=Depends(session)):
    r = rfq_access(db, id, user)
    subs = db.scalars(select(Submission).where(Submission.rfq_id == id)).all()
    return {
        **dump(r),
        "items": [dump(i) for i in db.scalars(select(Item).where(Item.rfq_id == id))],
        "submissions": [
            {
                **dump(s),
                "vendor": db.get(Vendor, s.vendor_id).name,
                "documents": [
                    dump(d) for d in db.scalars(select(Document).where(Document.submission_id == s.id))
                ],
            }
            for s in subs
        ],
    }


@app.patch("/rfqs/{id}")
def update_rfq(id: str, body: RFQIn, user=Depends(editor), db=Depends(session)):
    r = rfq_access(db, id, user)
    if r.status not in ("DRAFT", "OPEN"):
        raise HTTPException(409, "RFQ is locked during analysis/review")
    existing = db.scalars(select(Item).where(Item.rfq_id == id)).all()
    current = [{k: v for k, v in dump(item).items() if k not in ("id", "rfq_id")} for item in existing]
    proposed = [item.model_dump() for item in body.items]
    if current != proposed:
        if db.scalar(select(Submission.id).where(Submission.rfq_id == id)):
            raise HTTPException(409, "Item changes require a new RFQ once submissions exist")
        db.execute(delete(Item).where(Item.rfq_id == id))
        for item in proposed:
            db.add(Item(rfq_id=id, **item))
    for k, v in body.model_dump(exclude={"items"}).items():
        setattr(r, k, str(v) if k == "due_date" else v)
    audit(db, user, "UPDATE_RFQ", id)
    commit(db)
    return dump(r)


@app.patch("/rfqs/{id}/status")
def status(id: str, body: StatusIn, user=Depends(editor), db=Depends(session)):
    r = rfq_access(db, id, user)
    allowed = {"DRAFT": {"OPEN"}, "OPEN": {"DRAFT"}, "REJECTED": {"OPEN"}}
    if body.status not in allowed.get(r.status, set()):
        raise HTTPException(
            409, "Invalid lifecycle transition; analysis and decisions manage review/final states"
        )
    r.status = body.status
    audit(db, user, "RFQ_STATUS", id, {"status": body.status})
    commit(db)
    return dump(r)


@app.post("/rfqs/{id}/submissions")
def add_submission(id: str, body: SubmissionIn, user=Depends(analyst), db=Depends(session)):
    r = rfq_access(db, id, user)
    get(db, Vendor, body.vendor_id)
    if r.status not in ("DRAFT", "OPEN"):
        raise HTTPException(409, "RFQ is locked")
    s = Submission(rfq_id=id, vendor_id=body.vendor_id)
    db.add(s)
    db.flush()
    audit(db, user, "ADD_SUBMISSION", s.id)
    commit(db)
    return dump(s)


@app.post("/submissions/{id}/documents")
async def upload_document(
    id: str, type: str = Form(...), file: UploadFile = File(...), user=Depends(analyst), db=Depends(session)
):
    s = sub_access(db, id, user)
    if db.get(RFQ, s.rfq_id).status not in ("DRAFT", "OPEN"):
        raise HTTPException(409, "RFQ is locked")
    if type not in ("quotation", "contract", "compliance"):
        raise HTTPException(422, "Unknown document type")
    data = await file.read(MAX_UPLOAD + 1)
    validate_pdf(file.filename or "", file.content_type, data)
    d = upload(db, s, type, Path(file.filename).name, data)
    audit(db, user, "UPLOAD_DOCUMENT", d.id)
    commit(db)
    return dump(d)


@app.post("/documents/{id}/process")
def process_document(id: str, user=Depends(analyst), db=Depends(session)):
    d = doc_access(db, id, user)
    r = db.get(RFQ, db.get(Submission, d.submission_id).rfq_id)
    if r.status not in ("DRAFT", "OPEN"):
        raise HTTPException(409, "RFQ is locked")
    result = process(db, d)
    audit(db, user, "PROCESS_DOCUMENT", id)
    commit(db)
    return dump(result)


@app.get("/documents/{id}/findings")
def findings(id: str, user=Depends(current_user), db=Depends(session)):
    d = doc_access(db, id, user)
    quotation = d.metrics_json.get("quotation") or db.get(Submission, d.submission_id).extracted_json
    if (
        d.type != "quotation"
        or not quotation.get("evidence")
        or any(e["document_id"] != d.id for e in quotation["evidence"].values())
    ):
        quotation = {}
    return {
        "document": dump(d),
        "quotation": quotation,
        "chunks": [
            {k: v for k, v in dump(c).items() if k != "embedding"}
            for c in db.scalars(select(Chunk).where(Chunk.document_id == id))
        ],
        "findings": [dump(f) for f in db.scalars(select(Finding).where(Finding.document_id == id))],
    }


@app.get("/documents/{id}/file")
def document_file(id: str, user=Depends(current_user), db=Depends(session)):
    d = doc_access(db, id, user)
    return FileResponse(
        d.path, media_type="application/pdf", filename=d.original_name, content_disposition_type="inline"
    )


@app.get("/rfqs/{id}/evidence")
def evidence(
    id: str,
    q: str,
    vendor_id: str | None = None,
    type: str | None = None,
    user=Depends(current_user),
    db=Depends(session),
):
    rfq_access(db, id, user)
    return retrieve(db, id, q, vendor_id, type)


@app.post("/rfqs/{id}/analysis-runs")
def analysis(id: str, tasks: BackgroundTasks, user=Depends(analyst), db=Depends(session)):
    r = rfq_access(db, id, user)
    if r.status not in ("DRAFT", "OPEN", "REJECTED"):
        raise HTTPException(409, "RFQ already has an active or final analysis")
    run = Run(entity_id=id, model=settings.ollama_chat_model)
    db.add(run)
    db.flush()
    r.status = "ANALYZING"
    audit(db, user, "START_ANALYSIS", run.id)
    commit(db)
    tasks.add_task(execute, run.id)
    return dump(run)


@app.get("/analysis-runs/{id}")
def run_detail(id: str, user=Depends(current_user), db=Depends(session)):
    r = get(db, Run, id)
    rfq_access(db, r.entity_id, user)
    return {
        **dump(r),
        "outputs": [
            dump(o) for o in db.scalars(select(Output).where(Output.run_id == id).order_by(Output.started_at))
        ],
    }


@app.get("/rfqs/{id}/comparison")
def comparison(id: str, user=Depends(current_user), db=Depends(session)):
    rfq_access(db, id, user)
    rec = db.scalar(
        select(Recommendation)
        .where(Recommendation.rfq_id == id)
        .join(Run, Recommendation.run_id == Run.id)
        .order_by(Run.started_at.desc())
    )
    if not rec:
        return {"recommendation": None, "scores": []}
    return {"recommendation": dump(rec), **rec.payload_json}


@app.post("/recommendations/{id}/decision")
def decision(id: str, body: DecisionIn, tasks: BackgroundTasks, user=Depends(manager), db=Depends(session)):
    rec = get(db, Recommendation, id)
    r = rfq_access(db, rec.rfq_id, user)
    run = get(db, Run, rec.run_id)
    if rec.status != "PENDING" or run.status != "WAITING_APPROVAL":
        raise HTTPException(409, "Recommendation is not awaiting a decision")
    selected = body.vendor_id if body.decision == "override" else rec.preferred_vendor_id
    if body.decision != "reject" and not any(
        s["vendor_id"] == selected and s["eligible"] for s in rec.payload_json["scores"]
    ):
        raise HTTPException(422, "Chosen vendor must be an eligible submission")
    if body.decision != "reject":
        chosen = get(db, Vendor, selected)
        if chosen.mandatory_failure or chosen.compliance_status == "failed":
            raise HTTPException(
                409, "Vendor eligibility changed after analysis; reject and rerun the evaluation"
            )
    rec.status = {"approve": "APPROVED", "reject": "REJECTED", "override": "OVERRIDDEN"}[body.decision]
    rec.final_vendor_id = None if body.decision == "reject" else selected
    r.status = "REJECTED" if body.decision == "reject" else "APPROVED"
    db.add(Approval(recommendation_id=id, actor_id=user.id, decision=body.decision, reason=body.reason))
    audit(db, user, "MANAGER_DECISION", id, body.model_dump())
    commit(db)
    tasks.add_task(
        execute, run.id, {**body.model_dump(), "actor_id": user.id, "final_vendor_id": rec.final_vendor_id}
    )
    return dump(rec)


@app.post("/rfqs/{id}/reports")
def report(id: str, user=Depends(manager), db=Depends(session)):
    r = rfq_access(db, id, user)
    rec = db.scalar(
        select(Recommendation)
        .where(Recommendation.rfq_id == id, Recommendation.status.in_(["APPROVED", "OVERRIDDEN", "REJECTED"]))
        .join(Run, Recommendation.run_id == Run.id)
        .order_by(Run.started_at.desc())
    )
    if not rec:
        raise HTTPException(409, "A manager decision is required before final report")
    if db.get(Run, rec.run_id).status != "COMPLETED":
        raise HTTPException(409, "Report agent has not completed")
    existing = db.scalar(select(Report).where(Report.recommendation_id == rec.id))
    if existing:
        return dump(existing)
    approval = db.scalar(select(Approval).where(Approval.recommendation_id == rec.id))
    outputs = [dump(o) for o in db.scalars(select(Output).where(Output.run_id == rec.run_id))]
    files = make_report(
        "ProcureMind-" + r.number + "-" + rec.id,
        {
            "rfq": dump(r),
            "recommendation": dump(rec),
            "human_decision": dump(approval),
            "agent_outputs": outputs,
            "limitations": [
                "Prepared digital PDFs; no autonomous purchase orders; commercial review is advisory."
            ],
        },
    )
    result = Report(rfq_id=id, recommendation_id=rec.id, files_json=files)
    db.add(result)
    audit(db, user, "GENERATE_REPORT", id)
    commit(db)
    return dump(result)


@app.get("/reports/{id}/{format}")
def download_report(id: str, format: str, user=Depends(current_user), db=Depends(session)):
    report = get(db, Report, id)
    rfq_access(db, report.rfq_id, user)
    if format not in report.files_json:
        raise HTTPException(404, "Unknown report format")
    path = ROOT / "storage" / "reports" / report.files_json[format]
    return FileResponse(path, filename=path.name)


@app.get("/activity")
def activity(user=Depends(current_user), db=Depends(session)):
    from .core import Audit

    query = select(Audit).order_by(Audit.timestamp.desc()).limit(100)
    if user.role != "manager":
        query = query.where(Audit.actor_id == user.id)
    return [dump(a) for a in db.scalars(query)]
