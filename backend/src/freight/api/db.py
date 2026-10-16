"""Database tables. Every operational row belongs to one company (tenant)."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
    true,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(20), default="dispatcher")  # admin|dispatcher|viewer
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Operation(Base):
    """A company's current planning situation: sites, roads, fleet, jobs and rules."""

    __tablename__ = "operations"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    snapshot: Mapped[str] = mapped_column(Text)  # Snapshot JSON
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanRun(Base):
    """One planning run: the exact snapshot it used, its settings and its plan."""

    __tablename__ = "plan_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    settings: Mapped[str] = mapped_column(Text)  # JSON
    snapshot: Mapped[str] = mapped_column(Text)  # Snapshot JSON actually planned
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)  # Plan JSON
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WhatIfRun(Base):
    """A "what if?" question about one plan, answered by two re-plans in the background."""

    __tablename__ = "whatif_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    plan_run_id: Mapped[str] = mapped_column(ForeignKey("plan_runs.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    change: Mapped[str] = mapped_column(Text)  # JSON
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: facts and texts
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    """Who changed what, and when: every change to a company's data or plans."""

    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    action: Mapped[str] = mapped_column(String(40))  # e.g. "orders.upload", "rule.add"
    detail: Mapped[str] = mapped_column(Text, default="{}")  # JSON


class LoginFailure(Base):
    """A failed sign-in, kept briefly to slow down password guessing."""

    __tablename__ = "login_failures"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), index=True)
    address: Mapped[str] = mapped_column(String(64), index=True)  # client IP
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Database:
    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(url, connect_args=_connect_args(url))
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _sqlite_foreign_keys)
        self.session = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        add_missing_columns(self.engine)


def _connect_args(url: str) -> dict[str, object]:
    # The API answers requests on several threads; SQLite must allow that.
    return {"check_same_thread": False} if url.startswith("sqlite") else {}


def _sqlite_foreign_keys(connection: object, _: object) -> None:
    cursor = connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def add_missing_columns(engine: Engine) -> None:
    """Add columns introduced after a table was created (with their server default).

    A stand-in for full migrations while every new column has a default; switch to
    Alembic before the first change that needs more (renames, type changes).
    """
    existing = inspect(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if not existing.has_table(table.name):
                continue
            present = {c["name"] for c in existing.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                kind = column.type.compile(dialect=engine.dialect)
                default = getattr(column.server_default, "arg", None)
                clause = ""
                if default is not None:
                    value = (
                        default.compile(dialect=engine.dialect)
                        if hasattr(default, "compile")
                        else default
                    )
                    clause = f" DEFAULT {value}"
                connection.execute(
                    text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {kind}{clause}")
                )
