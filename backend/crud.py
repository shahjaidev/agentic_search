"""CRUD helpers for conversations, messages, enrichment jobs, and query logs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend import models
from backend.database import data_connection

POLYMARKET_TABLE = "polymarket_markets_enriched"


def _parse_end_date(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None

    # Normalize common ISO formats, handling trailing 'Z' or missing time components.
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        try:
            return datetime.fromisoformat(f"{text}T00:00:00")
        except ValueError:
            return None


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
        created_at=datetime.now(timezone.utc),
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
    job.updated_at = datetime.now(timezone.utc)
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
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


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
    with data_connection() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        return [row[1] for row in result]


def list_future_market_names(limit: int | None = None) -> list[str]:
    """Return future-dated market questions for supplemental context."""

    base_sql = f"""
        SELECT question
        FROM {POLYMARKET_TABLE}
        WHERE question IS NOT NULL
          AND question != ''
          AND end_date_iso IS NOT NULL
          AND date(end_date_iso) > DATE('now')
        ORDER BY question
    """
    if limit is not None and limit > 0:
        base_sql += "\n        LIMIT :limit"
    query = text(base_sql)
    params = {"limit": limit} if limit is not None and limit > 0 else {}
    with data_connection() as conn:
        result = conn.execute(query, params)
        return [row[0] for row in result]


def execute_sql(session: Session, sql: str, params: dict | None = None) -> list[dict]:
    params = params or {}
    with data_connection() as conn:
        result = conn.execute(text(sql), params)
        rows = [dict(row._mapping) for row in result]

    if not rows:
        return rows

    now = datetime.now(timezone.utc)
    filtered: list[dict] = []
    for row in rows:
        if "end_date_iso" not in row:
            filtered.append(row)
            continue
        end_value = _parse_end_date(row.get("end_date_iso"))
        if end_value is None:
            continue
        if end_value.tzinfo is None:
            end_value = end_value.replace(tzinfo=timezone.utc)
        if end_value > now:
            filtered.append(row)
    return filtered
