"""Database layer for the agentic search prototype."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from settings import get_settings


SETTINGS = get_settings()
ENGINE: Engine = create_engine(SETTINGS.database_url, future=True, echo=False)
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, future=True)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)
Base = declarative_base(metadata=metadata)


class Startup(Base):
    """Primary table containing startup records."""

    __tablename__ = "startups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    website = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ChatMessage(Base):
    """Chat history table."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_message = Column(Text, nullable=False)
    assistant_message = Column(Text, nullable=False)
    structured_response = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class EnrichmentJob(Base):
    """Queue of enrichment tasks."""

    __tablename__ = "enrichment_jobs"

    id = Column(Integer, primary_key=True, index=True)
    attribute_name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    payload = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ExecutedSQL(Base):
    """Persists executed SQL statements for auditing."""

    __tablename__ = "executed_sql"

    id = Column(Integer, primary_key=True, index=True)
    statement = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


@contextmanager
def session_scope():
    """Provide a transactional scope around operations."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - defensive rollback
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create tables if they do not yet exist."""

    Base.metadata.create_all(bind=ENGINE)


def column_exists(table_name: str, column_name: str) -> bool:
    """Return True if the column already exists on the table."""

    inspector = inspect(ENGINE)
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def add_text_column(table_name: str, column_name: str) -> None:
    """Add a nullable TEXT column to the specified table if missing."""

    if column_exists(table_name, column_name):
        return

    statement = text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} TEXT")
    record_sql_execution(statement.text)
    with ENGINE.begin() as connection:
        connection.execute(statement)


def record_sql_execution(sql_statement: str) -> None:
    """Persist executed SQL for auditing."""

    with session_scope() as session:
        session.add(ExecutedSQL(statement=sql_statement))


def enqueue_enrichment_job(attribute_name: str, payload: Optional[dict] = None) -> None:
    """Create a new enrichment job if one with the same attribute is not already pending."""

    with session_scope() as session:
        exists = (
            session.query(EnrichmentJob)
            .filter(EnrichmentJob.attribute_name == attribute_name, EnrichmentJob.status == "pending")
            .first()
        )
        if exists:
            return
        session.add(EnrichmentJob(attribute_name=attribute_name, payload=payload or {}))


def fetch_pending_jobs(limit: int = 10) -> Iterable[EnrichmentJob]:
    """Return pending enrichment jobs ordered by creation time."""

    with session_scope() as session:
        jobs = (
            session.query(EnrichmentJob)
            .filter(EnrichmentJob.status == "pending")
            .order_by(EnrichmentJob.created_at.asc())
            .limit(limit)
            .all()
        )
        for job in jobs:
            session.expunge(job)
        return jobs


def mark_job_complete(job_id: int) -> None:
    """Mark a job as complete."""

    with session_scope() as session:
        job = session.query(EnrichmentJob).get(job_id)
        if job:
            job.status = "complete"
            job.completed_at = datetime.utcnow()


def mark_job_failed(job_id: int, error_message: str) -> None:
    """Mark a job as failed and store the error."""

    with session_scope() as session:
        job = session.query(EnrichmentJob).get(job_id)
        if job:
            job.status = "failed"
            job.error = error_message
            job.completed_at = datetime.utcnow()


def ensure_startup_attribute(attribute_name: str) -> None:
    """Guarantee the startups table has a column for the attribute."""

    add_text_column(Startup.__tablename__, attribute_name)


def get_startup_ids() -> list[int]:
    """Return all startup ids."""

    with session_scope() as session:
        rows = session.query(Startup.id).all()
        return [row[0] for row in rows]


def update_startup_attribute(startup_id: int, attribute_name: str, value: str) -> None:
    """Update a single startup attribute value."""

    statement = text(
        f"UPDATE {Startup.__tablename__} SET {attribute_name} = :value WHERE id = :startup_id"
    )
    with ENGINE.begin() as connection:
        connection.execute(statement, {"value": value, "startup_id": startup_id})
    record_sql_execution(statement.text)


def upsert_startup(name: str, description: str | None = None, website: str | None = None) -> Startup:
    """Create or update a startup record."""

    with session_scope() as session:
        startup = session.query(Startup).filter(Startup.name == name).first()
        if startup:
            startup.description = description or startup.description
            startup.website = website or startup.website
            session.flush()
            session.refresh(startup)
            session.expunge(startup)
            return startup
        startup = Startup(name=name, description=description, website=website)
        session.add(startup)
        session.flush()
        session.refresh(startup)
        session.expunge(startup)
        return startup


def list_chat_messages(limit: int = 50) -> list[ChatMessage]:
    """Return recent chat messages."""

    with session_scope() as session:
        rows = (
            session.query(ChatMessage)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def add_chat_message(user_message: str, assistant_message: str, structured_response: dict) -> None:
    """Persist a chat message."""

    with session_scope() as session:
        session.add(
            ChatMessage(
                user_message=user_message,
                assistant_message=assistant_message,
                structured_response=structured_response,
            )
        )
