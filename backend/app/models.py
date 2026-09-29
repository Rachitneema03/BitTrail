"""SQLAlchemy models. See docs/schema.md for the field-level spec."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, TypeDecorator, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo on read)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


UTC = UTCDateTime()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    role: Mapped[str] = mapped_column(String(20))  # io | analyst | vasp
    vasp_id: Mapped[str | None] = mapped_column(ForeignKey("vasps.id"), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTC, default=now)


class Vasp(Base):
    __tablename__ = "vasps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(40), default="exchange")
    country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fiu_ind_registered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    on_sahyog: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    le_portal_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    nodal_contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Label(Base):
    __tablename__ = "labels"
    __table_args__ = (
        UniqueConstraint("chain", "address", "type", "source", name="uq_label"),
        Index("ix_labels_chain_address", "chain", "address"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chain: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))
    vasp_id: Mapped[str | None] = mapped_column(ForeignKey("vasps.id"), nullable=True)
    entity_name: Mapped[str] = mapped_column(String(120))
    tier: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40))
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTC, default=now)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_no: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fir_no: Mapped[str] = mapped_column(String(60))
    ncrp_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    police_station: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fraud_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fraud_time: Mapped[datetime] = mapped_column(UTC)
    amount_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTC, default=now)
    updated_at: Mapped[datetime] = mapped_column(UTC, default=now, onupdate=now)


class CaseWallet(Base):
    __tablename__ = "case_wallets"
    __table_args__ = (UniqueConstraint("case_id", "chain", "address", name="uq_case_wallet"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    chain: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(100))
    victim_tx_hash: Mapped[str | None] = mapped_column(String(120), nullable=True)


class TraceJob(Base):
    __tablename__ = "trace_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    chain_heights: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(UTC, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTC, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTC, default=now)


class TraceNode(Base):
    __tablename__ = "trace_nodes"
    __table_args__ = (UniqueConstraint("job_id", "chain", "address", name="uq_trace_node"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("trace_jobs.id", ondelete="CASCADE"), index=True)
    chain: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    depth: Mapped[int] = mapped_column(Integer)
    value_share: Mapped[float] = mapped_column(Float, default=0.0)
    value_usd: Mapped[float] = mapped_column(Float, default=0.0)
    entity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    label_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    label_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


class TraceEdge(Base):
    __tablename__ = "trace_edges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("trace_jobs.id", ondelete="CASCADE"), index=True)
    chain: Mapped[str] = mapped_column(String(20))
    from_address: Mapped[str] = mapped_column(String(100))
    to_address: Mapped[str] = mapped_column(String(100))
    asset: Mapped[str] = mapped_column(String(20))
    amount_usd: Mapped[float] = mapped_column(Float)
    value_share: Mapped[float] = mapped_column(Float)
    tx_hashes: Mapped[list] = mapped_column(JSON, default=list)
    tx_count: Mapped[int] = mapped_column(Integer, default=1)
    first_ts: Mapped[datetime] = mapped_column(UTC)
    block: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(String(10), default="forward")  # forward | backward | sweep


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("trace_jobs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    vasp_id: Mapped[str | None] = mapped_column(ForeignKey("vasps.id"), nullable=True)
    vasp_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(10))  # off_ramp | on_ramp
    chain: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(100))
    address_kind: Mapped[str] = mapped_column(String(20))
    hops: Mapped[int] = mapped_column(Integer)
    value_share: Mapped[float] = mapped_column(Float)
    value_usd: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    actionability: Mapped[float] = mapped_column(Float)
    rank_score: Mapped[float] = mapped_column(Float)
    funds_status: Mapped[str] = mapped_column(String(20), default="unknown")
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    evidence_tx: Mapped[list] = mapped_column(JSON, default=list)
    path: Mapped[list] = mapped_column(JSON, default=list)


class AddressCaseIndex(Base):
    __tablename__ = "address_case_index"
    chain: Mapped[str] = mapped_column(String(20), primary_key=True)
    address: Mapped[str] = mapped_column(String(100), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    value_share: Mapped[float] = mapped_column(Float)
    job_id: Mapped[str] = mapped_column(String(36))


class CaseLink(Base):
    __tablename__ = "case_links"
    __table_args__ = (UniqueConstraint("case_a", "case_b", "chain", "address", name="uq_case_link"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_a: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    case_b: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    chain: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    entity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTC, default=now)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(ForeignKey("trace_jobs.id", ondelete="CASCADE"))
    manifest: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTC, default=now)


class Request(Base):
    __tablename__ = "requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    vasp_id: Mapped[str | None] = mapped_column(ForeignKey("vasps.id"), nullable=True)
    vasp_name: Mapped[str] = mapped_column(String(120))
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(30))
    legal_basis: Mapped[str] = mapped_column(String(120))
    chain: Mapped[str] = mapped_column(String(20))
    addresses: Mapped[list] = mapped_column(JSON, default=list)
    body_md: Mapped[str] = mapped_column(Text)
    report_id: Mapped[str | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    sahyog_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTC, default=now)
    sent_at: Mapped[datetime | None] = mapped_column(UTC, nullable=True)


class VaspReply(Base):
    __tablename__ = "vasp_replies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), unique=True)
    outcome: Mapped[str] = mapped_column(String(20))  # confirmed | denied
    account_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    frozen_amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    replied_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    replied_at: Mapped[datetime] = mapped_column(UTC, default=now)


class WatchItem(Base):
    __tablename__ = "watch_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    chain: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(30))
    entity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime] = mapped_column(UTC, default=now)
    last_seen_tx: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    watch_item_id: Mapped[str | None] = mapped_column(ForeignKey("watch_items.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTC, default=now)


class ApiCache(Base):
    __tablename__ = "api_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30))
    request: Mapped[dict] = mapped_column(JSON)
    response: Mapped[dict | list] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(UTC, default=now)
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Price(Base):
    __tablename__ = "prices"
    asset: Mapped[str] = mapped_column(String(10), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    usd: Mapped[float] = mapped_column(Float)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(UTC, default=now)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
