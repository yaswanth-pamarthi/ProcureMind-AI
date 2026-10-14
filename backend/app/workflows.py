import sqlite3, threading
from typing import TypedDict
from sqlalchemy import select
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from .core import ROOT, Session, uid, now
from .models import (
    RFQ,
    Submission,
    Vendor,
    Performance,
    Document,
    Finding,
    Run,
    Output,
    Recommendation,
    Score,
    Chunk,
)
from .ai import commentary
from .scoring import score_vendors, vendor_risk
from .documents import retrieve


class State(TypedDict, total=False):
    rfq_id: str
    run_id: str
    vendor: dict
    quotation: dict
    contract: dict
    risk: dict
    spend: dict
    recommendation_id: str
    decision: dict
    report: dict


def context(db, rfq_id):
    rfq = db.get(RFQ, rfq_id)
    rows = []
    submissions = db.scalars(select(Submission).where(Submission.rfq_id == rfq_id)).all()
    if len(submissions) < 2:
        raise ValueError("At least two submissions are required for comparison")
    for s in submissions:
        docs = db.scalars(select(Document).where(Document.submission_id == s.id)).all()
        if not any(d.type == "quotation" and d.parse_status == "PROCESSED" for d in docs) or any(
            d.parse_status != "PROCESSED" for d in docs
        ):
            raise ValueError("Required documents are missing or unprocessed: NEEDS_INPUT")
        vendor = db.get(Vendor, s.vendor_id)
        history = db.scalars(
            select(Performance).where(Performance.vendor_id == vendor.id, Performance.metric == "quality")
        ).all()
        findings = db.scalars(select(Finding).where(Finding.document_id.in_([d.id for d in docs]))).all()
        q = s.extracted_json
        if not q:
            raise ValueError("Structured quotation values missing")
        contract_docs = [d.id for d in docs if d.type == "contract"]
        contract_text = (
            " ".join(db.scalars(select(Chunk.text).where(Chunk.document_id.in_(contract_docs))).all()).lower()
            if contract_docs
            else ""
        )
        expected_clauses = [
            "termination",
            "payment",
            "liability",
            "warranty",
            "penalties",
            "renewal",
            "confidentiality",
            "governing law",
            "data protection",
        ]
        rows.append(
            {
                "submission_id": s.id,
                "vendor_id": vendor.id,
                "vendor": vendor.name,
                "total": s.total,
                "currency": s.currency,
                "delivery_days": q["delivery_days"],
                "quality": sum(h.value for h in history) / len(history) if history else None,
                "history_sources": [h.source for h in history],
                "compliance": vendor.compliance_status,
                "profile_risk": vendor.risk_level,
                "mandatory_failure": vendor.mandatory_failure,
                "penalty": sum(f.payload_json["penalty"] for f in findings),
                "findings": [
                    {"category": f.category, "finding": f.finding, "severity": f.severity, **f.payload_json}
                    for f in findings
                ],
                "quotation": q,
                "document_ids": [d.id for d in docs],
                "missing_clauses": [clause for clause in expected_clauses if clause not in contract_text],
            }
        )
    if not db.scalar(
        select(Document.id)
        .join(Submission)
        .where(Submission.rfq_id == rfq.id, Document.type == "contract", Document.parse_status == "PROCESSED")
    ):
        raise ValueError("At least one processed contract is required: NEEDS_INPUT")
    if any(r["currency"] != rfq.currency for r in rows):
        raise ValueError("Mixed currency/RFQ mismatch: provide conversion policy")
    return rfq, rows


def record(state, name, payload, ids, started):
    summary, metadata = commentary(name, payload, ids)
    with Session() as db:
        db.add(
            Output(
                run_id=state["run_id"],
                agent_name=name,
                payload_json={**payload, "ai_commentary": summary},
                inputs_json={"evidence_ids": ids, "entity_id": state["rfq_id"]},
                model_json=metadata,
                started_at=started,
                completed_at=now(),
            )
        )
        db.commit()
    return {**payload, "ai_commentary": summary}


def supervisor(state):
    start = now()
    with Session() as db:
        rfq, rows = context(db, state["rfq_id"])
    record(
        state,
        "Supervisor",
        {
            "plan": ["vendor", "quotation", "contract", "risk", "spend", "human_review", "report"],
            "submissions": len(rows),
            "validation_errors": [],
        },
        [],
        start,
    )
    return {}


def vendor(state):
    start = now()
    with Session() as db:
        _, rows = context(db, state["rfq_id"])
    payload = {
        "vendors": [
            {
                k: r[k]
                for k in [
                    "vendor_id",
                    "vendor",
                    "quality",
                    "history_sources",
                    "compliance",
                    "mandatory_failure",
                ]
            }
            for r in rows
        ]
    }
    return {"vendor": record(state, "Vendor Intelligence", payload, [r["vendor_id"] for r in rows], start)}


def quotation(state):
    start = now()
    with Session() as db:
        _, rows = context(db, state["rfq_id"])
    payload = {
        "quotations": [
            {k: r[k] for k in ["vendor", "total", "currency", "delivery_days", "quotation"]} for r in rows
        ]
    }
    ids = [e["chunk_id"] for r in rows for e in r["quotation"]["evidence"].values()]
    return {"quotation": record(state, "Quotation Comparison", payload, list(set(ids)), start)}


def contract(state):
    start = now()
    with Session() as db:
        _, rows = context(db, state["rfq_id"])
        evidence = retrieve(
            db, state["rfq_id"], "termination liability payment data protection", kind="contract"
        )
    payload = {
        "findings": [{**f, "vendor": r["vendor"]} for r in rows for f in r["findings"]],
        "retrieved_evidence": evidence,
        "missing_clauses": {r["vendor"]: r["missing_clauses"] for r in rows},
        "limitations": [
            "Clause rules cover prepared digital contracts; absence is not proof of legal compliance."
        ],
    }
    ids = [c["chunk_id"] for c in evidence] + [f["evidence"]["chunk_id"] for f in payload["findings"]]
    return {"contract": record(state, "Contract Analysis", payload, list(set(ids)), start)}


def risk(state):
    start = now()
    with Session() as db:
        rfq, rows = context(db, state["rfq_id"])
        scores = score_vendors(rows, rfq.weights_json)
        for row in scores:
            for factor in row["breakdown"]:
                db.add(Score(run_id=state["run_id"], submission_id=row["submission_id"], **factor))
        preferred = next(r for r in scores if r["eligible"])
        rec = Recommendation(
            id=uid(),
            rfq_id=rfq.id,
            run_id=state["run_id"],
            preferred_vendor_id=preferred["vendor_id"],
            payload_json={
                "scores": scores,
                "rationale": "Highest deterministic score among eligible vendors.",
                "alternatives": [r["vendor"] for r in scores if r["vendor_id"] != preferred["vendor_id"]],
                "missing_data": [],
            },
        )
        db.add(rec)
        db.commit()
        rec_id = rec.id
    payload = {
        "risk_register": [
            {
                "vendor": r["vendor"],
                **vendor_risk(r),
                "mitigation": "Negotiate identified clauses; verify compliance before award.",
                "findings": r["findings"],
            }
            for r in rows
        ],
        "scores": scores,
        "preferred_vendor": preferred["vendor"],
        "recommendation_id": rec_id,
    }
    return {
        "risk": record(
            state,
            "Risk Assessment",
            payload,
            [f["evidence"]["chunk_id"] for r in rows for f in r["findings"]],
            start,
        ),
        "recommendation_id": rec_id,
    }


def spend(state):
    start = now()
    with Session() as db:
        rfq, rows = context(db, state["rfq_id"])
    payload = {
        "budget": rfq.budget,
        "currency": rfq.currency,
        "budget_variance": [
            {
                "vendor": r["vendor"],
                "variance": r["total"] - rfq.budget,
                "savings_against_budget": rfq.budget - r["total"],
            }
            for r in rows
        ],
        "historical_forecast": None,
        "limitations": ["No historic spend forecast without historic spend records."],
    }
    return {"spend": record(state, "Spend Analytics", payload, [], start)}


def human_review(state):
    decision = interrupt(
        {"recommendation_id": state["recommendation_id"], "requires_role": "manager", "reason_required": True}
    )
    return {"decision": decision}


def report(state):
    start = now()
    payload = {
        "manager_decision": state["decision"],
        "recommendation_id": state["recommendation_id"],
        "summary": "Human decision preserved alongside the original recommendation.",
        "scores": state["risk"]["scores"],
    }
    return {"report": record(state, "Report Generation", payload, [], start)}


ROOT.joinpath("storage").mkdir(exist_ok=True)
connection = sqlite3.connect(ROOT / "storage" / "workflow-checkpoints.sqlite", check_same_thread=False)
graph = StateGraph(State)
for name, node in [
    ("supervisor", supervisor),
    ("vendor", vendor),
    ("quotation", quotation),
    ("contract", contract),
    ("risk", risk),
    ("spend", spend),
    ("human_review", human_review),
    ("report", report),
]:
    graph.add_node(name, node)
graph.add_edge(START, "supervisor")
for specialist in ["vendor", "quotation", "contract"]:
    graph.add_edge("supervisor", specialist)
graph.add_edge(["vendor", "quotation", "contract"], "risk")
for a, b in [("risk", "spend"), ("spend", "human_review"), ("human_review", "report")]:
    graph.add_edge(a, b)
graph.add_edge("report", END)
workflow = graph.compile(checkpointer=SqliteSaver(connection))
lock = threading.Lock()


def execute(run_id, resume=None):
    with lock:
        with Session() as db:
            run = db.get(Run, run_id)
            entity = run.entity_id
            if resume is None and run.status != "RUNNING":
                return
        try:
            value = workflow.invoke(
                Command(resume=resume) if resume is not None else {"rfq_id": entity, "run_id": run_id},
                config={"configurable": {"thread_id": run_id}},
            )
            with Session() as db:
                run = db.get(Run, run_id)
                rfq = db.get(RFQ, entity)
                run.status = "WAITING_APPROVAL" if "__interrupt__" in value else "COMPLETED"
                run.completed_at = now()
                if run.status == "WAITING_APPROVAL":
                    rfq.status = "REVIEW"
                db.commit()
        except Exception as exc:
            with Session() as db:
                run = db.get(Run, run_id)
                run.status = "NEEDS_INPUT" if "NEEDS_INPUT" in str(exc) else "FAILED"
                run.error = str(exc)[:2000]
                run.completed_at = now()
                db.get(RFQ, entity).status = "OPEN"
                db.commit()
