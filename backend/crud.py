"""CRUD helpers for conversations, messages, enrichment jobs, and query logs."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend import models


def get_conversation(session: Session, conversation_id: Optional[str]) -> Optional[models.Conversation]:
    if not conversation_id:
        return None
    stmt = select(models.Conversation).where(models.Conversation.id == conversation_id)
    return session.scalars(stmt).first()


def create_conversation(
    session: Session, conversation_id: Optional[str] = None, title: Optional[str] = None
) -> models.Conversation:
    conversation = models.Conversation(id=conversation_id or generate_conversation_id(), title=title)
    session.add(conversation)
    session.flush()
    return conversation


def add_message(
    session: Session,
    conversation: models.Conversation,
    role: str,
    content: str,
    payload: Optional[dict] = None,
) -> models.Message:
    message = models.Message(
        conversation=conversation,
        role=role,
        content=content,
        payload=payload,
        created_at=datetime.utcnow(),
    )
    session.add(message)
    session.flush()
    return message


def enqueue_enrichment(
    session: Session,
    conversation: Optional[models.Conversation],
    attribute: Optional[str],
    payload: Optional[dict],
    notes: Optional[str] = None,
) -> models.EnrichmentJob:
    job = models.EnrichmentJob(
        conversation=conversation,
        attribute=attribute,
        payload=payload or {},
        status="pending",
        notes=notes,
    )
    session.add(job)
    session.flush()
    return job


def mark_enrichment_complete(session: Session, job: models.EnrichmentJob, notes: str | None = None) -> None:
    job.status = "complete"
    if notes:
        job.notes = notes
    job.updated_at = datetime.utcnow()
    session.add(job)


def add_query_log(
    session: Session,
    conversation: models.Conversation,
    sql_text: str,
    results: list[dict],
    columns_considered: list[str],
    missing_columns: list[str],
) -> models.QueryLog:
    log = models.QueryLog(
        conversation=conversation,
        sql_text=sql_text,
        results=results,
        columns_considered=columns_considered,
        missing_columns=missing_columns,
    )
    session.add(log)
    session.flush()
    return log


def get_query_logs(session: Session, conversation: models.Conversation) -> list[models.QueryLog]:
    stmt = select(models.QueryLog).where(models.QueryLog.conversation_id == conversation.id).order_by(models.QueryLog.id)
    return list(session.scalars(stmt))


def generate_conversation_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d%H%M%S%f")


def serialize_messages(messages: Iterable[models.Message]) -> list[dict]:
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "payload": message.payload,
            "created_at": message.created_at,
        }
        for message in messages
    ]


def list_columns(session: Session, table_name: str) -> list[str]:
    result = session.execute(text(f"PRAGMA table_info({table_name})"))
    return [row[1] for row in result]


def execute_sql(session: Session, sql: str, params: dict | None = None) -> list[dict]:
    params = params or {}
    result = session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


