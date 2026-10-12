"""PostgreSQL storage. Every operational record is qualified by tenant."""

from datetime import datetime
from functools import lru_cache
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from freight.settings import get_settings


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(150))


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    issuer: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(255))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint("role IN ('viewer', 'dispatcher')", name="membership_role"),)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(255), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(default=True)


class Workspace(Base):
    __tablename__ = "workspaces"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Revision(Base):
    __tablename__ = "revisions"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Audit(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str | None] = mapped_column(String(600))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    base_version: Mapped[int] = mapped_column(Integer)
    entity: Mapped[str] = mapped_column(String(30))
    source_name: Mapped[str] = mapped_column(String(150))
    checksum: Mapped[str] = mapped_column(String(64))
    raw_csv: Mapped[str] = mapped_column(Text)
    mapping: Mapped[dict[str, str]] = mapped_column(JSONB)
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceRow(Base):
    __tablename__ = "source_rows"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    entity: Mapped[str] = mapped_column(String(30), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(210), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)


class MappingProfile(Base):
    __tablename__ = "mapping_profiles"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), primary_key=True)
    entity: Mapped[str] = mapped_column(String(30))
    mapping: Mapped[dict[str, str]] = mapped_column(JSONB)


class Idempotency(Base):
    __tablename__ = "idempotency_keys"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "revision"], ["revisions.tenant_id", "revisions.version"]
        ),
        UniqueConstraint("id"),
        Index("ix_runs_tenant_created", "tenant_id", "created_at"),
    )
    tenant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    diagnostic: Mapped[bool] = mapped_column(default=False)
    seconds: Mapped[int] = mapped_column(Integer, default=10)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RuleProposal(Base):
    __tablename__ = "rule_proposals"
    __table_args__ = (Index("ix_proposals_tenant_created", "tenant_id", "created_at"),)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    base_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@lru_cache
def session_factory() -> sessionmaker[Session]:
    url = get_settings().database_url
    options = (
        str(make_url(url).query.get("options", ""))
        + " -c statement_timeout=15000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000"
    )
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        pool_recycle=1800,
        connect_args={"connect_timeout": 5, "options": options},
    )
    return sessionmaker(engine, expire_on_commit=False)
