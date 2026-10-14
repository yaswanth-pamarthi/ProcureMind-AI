from datetime import datetime
from sqlalchemy import String, Float, Integer, Boolean, ForeignKey, JSON, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from .core import Base, uid, now


class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, unique=True)
    country: Mapped[str] = mapped_column(String, default="India")
    category: Mapped[str] = mapped_column(String, default="IT equipment")
    compliance_status: Mapped[str] = mapped_column(String, default="compliant")
    mandatory_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_level: Mapped[str] = mapped_column(String, default="low")


class Performance(Base):
    __tablename__ = "vendor_performance"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    metric: Mapped[str] = mapped_column(String, default="quality")
    value: Mapped[float] = mapped_column(Float)
    period: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)


class RFQ(Base):
    __tablename__ = "rfqs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    number: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String)
    budget: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="INR")
    due_date: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="DRAFT")
    weights_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Item(Base):
    __tablename__ = "rfq_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    rfq_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"))
    description: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String, default="piece")
    target_price: Mapped[float] = mapped_column(Float)


class Submission(Base):
    __tablename__ = "vendor_submissions"
    __table_args__ = (UniqueConstraint("rfq_id", "vendor_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    rfq_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"))
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    status: Mapped[str] = mapped_column(String, default="UPLOADED")
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_json: Mapped[dict] = mapped_column(JSON, default=dict)


class QuotationItem(Base):
    __tablename__ = "quotation_items"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("vendor_submissions.id"))
    rfq_item_id: Mapped[str] = mapped_column(ForeignKey("rfq_items.id"))
    unit_price: Mapped[float] = mapped_column(Float)
    tax: Mapped[float] = mapped_column(Float)
    delivery_days: Mapped[int] = mapped_column(Integer)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("submission_id", "hash", "type"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("vendor_submissions.id"))
    type: Mapped[str] = mapped_column(String)
    original_name: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    hash: Mapped[str] = mapped_column(String)
    parse_status: Mapped[str] = mapped_column(String, default="UPLOADED")
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Chunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(String)
    text_hash: Mapped[str] = mapped_column(String)
    embedding: Mapped[list] = mapped_column(Vector(768))


class Finding(Base):
    __tablename__ = "contract_findings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    evidence_chunk_id: Mapped[str] = mapped_column(ForeignKey("document_chunks.id"))
    category: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    finding: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict] = mapped_column(JSON)


class Run(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"))
    workflow: Mapped[str] = mapped_column(String, default="procurement-v1")
    status: Mapped[str] = mapped_column(String, default="RUNNING")
    model: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Output(Base):
    __tablename__ = "agent_outputs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    agent_name: Mapped[str] = mapped_column(String)
    schema_version: Mapped[str] = mapped_column(String, default="1.0")
    prompt_version: Mapped[str] = mapped_column(String, default="grounded-v1")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    payload_json: Mapped[dict] = mapped_column(JSON)
    inputs_json: Mapped[dict] = mapped_column(JSON)
    model_json: Mapped[dict] = mapped_column(JSON)


class Score(Base):
    __tablename__ = "vendor_scores"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"))
    submission_id: Mapped[str] = mapped_column(ForeignKey("vendor_submissions.id"))
    factor: Mapped[str] = mapped_column(String)
    raw: Mapped[float] = mapped_column(Float)
    normalized: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    contribution: Mapped[float] = mapped_column(Float)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    rfq_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), unique=True)
    preferred_vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id"))
    final_vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    payload_json: Mapped[dict] = mapped_column(JSON)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"), unique=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    rfq_id: Mapped[str] = mapped_column(ForeignKey("rfqs.id"))
    recommendation_id: Mapped[str] = mapped_column(ForeignKey("recommendations.id"), unique=True)
    files_json: Mapped[dict] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
