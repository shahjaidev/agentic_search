"""FastAPI application exposing chat endpoints for the Agentic Search backend."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend import crud, models  # noqa: F401
from backend.database import Base, engine, get_session
from backend.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationRead,
    EnrichmentAction,
    GeminiResponse,
    MessagePayload,
    MessageRead,
    SqlExecutionResult,
    SqlPlan,
)
from backend.service_gemini import get_gemini_client

TABLE_NAME = "polymarket_markets_enriched"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "chat_runs.jsonl"
logger = logging.getLogger(__name__)
FUTURE_MARKET_CONTEXT_LIMIT = 0


def append_chat_log(payload: Dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")
    except Exception as exc:  # pragma: no cover - log but never break the response
        logger.error("Failed to write chat log: %s", exc)


def build_history_summary(conversation: models.Conversation) -> List[dict[str, str]]:
    summary = []
    for message in conversation.messages[-10:]:
        summary.append({"role": message.role, "content": message.content})
    return summary


app = FastAPI(title="Agentic Search Backend", version="0.2.0")


@app.on_event("startup")
def startup_event() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health", tags=["core"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest, session: Session = Depends(get_session)):
    gemini = get_gemini_client()

    conversation = crud.get_conversation(session, request.conversation_id)
    if conversation is None:
        conversation = crud.create_conversation(session, request.conversation_id)

    crud.add_message(session, conversation, role="user", content=request.message)

    available_columns = crud.list_columns(session, TABLE_NAME)
    debug_info = {
        "stage": "planning",
        "columns_available": available_columns,
        "columns_after_enrichment": available_columns,
        "enrichment_messages": [],
        "enrichment_actions": [],
        "initial_gemini": None,
        "followup_gemini": None,
        "plan": None,
        "result_row_count": 0,
        "history": build_history_summary(conversation),
        "pending_columns": [],
    }

    gemini = get_gemini_client()
    conversation_history = debug_info["history"]

    gemini_payload_raw = gemini.run_chat(available_columns, request.message, conversation_history)
    debug_info["initial_gemini"] = gemini_payload_raw
    try:
        gemini_payload = GeminiResponse.coerce(gemini_payload_raw)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    missing_columns: list[str] = []
    enrichment_messages: list[str] = []

    if gemini_payload.sql:
        sql_lower = gemini_payload.sql.lower()
        for col in gemini_payload.suggested_sql_columns:
            if col in available_columns:
                continue
            alias_pattern = f" as {col.lower()}"
            if alias_pattern in sql_lower:
                continue
            missing_columns.append(col)
    if gemini_payload.enrichment_hint:
        missing_attr = gemini_payload.enrichment_hint.get("attribute")
        if missing_attr and missing_attr not in available_columns:
            missing_columns.append(missing_attr)

    unique_missing = sorted(set(missing_columns))
    enrichment_actions: list[EnrichmentAction] = []

    if unique_missing:
        debug_info["stage"] = "enriching"
    for col in unique_missing:
        note = f"Auto-enrichment requested to add column '{col}'."
        job = crud.enqueue_enrichment(session, conversation, attribute=col, payload={}, notes=note)
        job.status = "pending_external"
        job.notes = "Awaiting external enrichment"
        enrichment_messages.append(f"Queued enrichment for column '{col}'")
        enrichment_actions.append(EnrichmentAction(attribute=col, reason=note))

    updated_columns = crud.list_columns(session, TABLE_NAME)
    debug_info.update(
        {
            "columns_after_enrichment": updated_columns,
            "enrichment_messages": enrichment_messages,
            "enrichment_actions": [action.model_dump() for action in enrichment_actions],
            "pending_columns": unique_missing,
        }
    )

    sql_results: List[Dict[str, Any]] = []
    batch_results: List[Dict[str, Any]] = []
    execution_summary = SqlExecutionResult()
    plan: SqlPlan | None = None
    top_n = max(1, min(gemini_payload.top_n or 10, 100))

    missing_after_enrichment = [col for col in unique_missing if col not in updated_columns]
    debug_info["pending_columns"] = missing_after_enrichment

    if not gemini_payload.sql and not gemini_payload.sql_batch and unique_missing:
        debug_info["stage"] = "awaiting_enrichment"

    if gemini_payload.sql_batch:
        debug_info["stage"] = "querying"
        debug_info["plan"] = {
            "type": "batch",
            "top_n": top_n,
            "queries": [item.model_dump() for item in gemini_payload.sql_batch],
        }

        if missing_after_enrichment:
            debug_info["stage"] = "awaiting_enrichment"
        else:
            for idx, item in enumerate(gemini_payload.sql_batch, start=1):
                statement = item.sql
                params = item.sql_variables or {}
                result_rows = crud.execute_sql(session, statement, params)
                sql_results.extend(result_rows)
                batch_entry = {
                    "name": item.name or f"query_{idx}",
                    "sql": statement,
                    "row_count": len(result_rows),
                    "rows": result_rows,
                }
                batch_results.append(batch_entry)
                crud.add_query_log(
                    session,
                    conversation,
                    statement,
                    result_rows,
                    available_columns,
                    unique_missing,
                )

            execution_summary = SqlExecutionResult(
                rows=sql_results,
                row_count=len(sql_results),
                preview_columns=list(sql_results[0].keys()) if sql_results else [],
            )
            debug_info["result_row_count"] = execution_summary.row_count
            debug_info["batch_results_preview"] = [
                {"name": entry["name"], "row_count": entry["row_count"]}
                for entry in batch_results
            ]

    elif gemini_payload.sql:
        try:
            plan = SqlPlan(
                sql=gemini_payload.sql,
                columns_considered=available_columns,
                missing_columns=unique_missing,
                suggested_columns=gemini_payload.suggested_sql_columns,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        debug_info["plan"] = plan.model_dump()
        debug_info["stage"] = "querying"

        if missing_after_enrichment:
            debug_info["stage"] = "awaiting_enrichment"
        else:
            params = gemini_payload.sql_variables or {}
            sql_results = crud.execute_sql(session, plan.sql, params)
            execution_summary = SqlExecutionResult(
                rows=sql_results,
                row_count=len(sql_results),
                preview_columns=list(sql_results[0].keys()) if sql_results else [],
            )
            crud.add_query_log(session, conversation, plan.sql, sql_results, plan.columns_considered, plan.missing_columns)
            debug_info["result_row_count"] = execution_summary.row_count

    followup_message = gemini_payload.final_message()
    followup_facts = gemini_payload.facts
    followup_raw = None

    if not gemini_payload.sql and unique_missing:
        followup_message = (
            "We requested enrichment for missing columns: "
            + ", ".join(unique_missing)
            + ". I'll follow up once the data is ready."
        )

    if (plan and sql_results) or (batch_results and sql_results):
        debug_info["stage"] = "answering"
        context = {
            "columns_available": available_columns,
            "columns_after_enrichment": updated_columns,
            "enrichment_messages": enrichment_messages,
            "pending_columns": debug_info.get("pending_columns", []),
            "batch_results": batch_results,
            "top_n": top_n,
        }
        future_market_names: list[str] = []
        if FUTURE_MARKET_CONTEXT_LIMIT > 0:
            future_market_names = crud.list_future_market_names(limit=FUTURE_MARKET_CONTEXT_LIMIT)
        if future_market_names:
            context["future_market_names"] = future_market_names
        debug_info["future_market_names_preview"] = future_market_names
        debug_info["future_market_names_limit"] = FUTURE_MARKET_CONTEXT_LIMIT
        followup_sql = plan.sql if plan else (batch_results[0]["sql"] if batch_results else "")
        followup_raw = gemini.run_answer_with_results(request.message, followup_sql, sql_results, context, conversation_history)
        followup_parsed = GeminiResponse.coerce(followup_raw, require_message=False)
        if followup_parsed.final_message():
            followup_message = followup_parsed.final_message()
            followup_facts = followup_parsed.facts or followup_facts
        if followup_parsed.final_table_rows:
            sql_results = followup_parsed.final_table_rows
        top_n = max(1, min(followup_parsed.top_n or top_n, 100))
        debug_info["selected_top_n"] = top_n
        debug_info["followup_gemini"] = followup_raw
    elif plan and not sql_results:
        pending_cols = debug_info.get("pending_columns", [])
        debug_info["stage"] = "awaiting_enrichment"
        if pending_cols:
            followup_message = (
                "We queued enrichment to fetch missing columns: "
                + ", ".join(pending_cols)
                + ". I'll answer once that data arrives."
            )
    elif batch_results and not sql_results:
        pending_cols = debug_info.get("pending_columns", [])
        debug_info["stage"] = "awaiting_enrichment"
        if pending_cols:
            followup_message = (
                "We queued enrichment to fetch missing columns: "
                + ", ".join(pending_cols)
                + ". I'll answer once that data arrives."
            )

    debug_info.setdefault("selected_top_n", top_n)

    response_payload = MessagePayload(
        facts=followup_facts,
        suggested_sql_columns=[],
        enrichment_hint=gemini_payload.enrichment_hint,
        sql=plan.sql if plan else None,
        sql_rows=sql_results[:top_n] if sql_results else [],
        sql_summary=followup_message,
        sql_batch=[
            {
                "name": entry.get("name"),
                "sql": entry.get("sql"),
                "row_count": entry.get("row_count"),
            }
            for entry in batch_results
        ],
        top_n=top_n,
        final_table_rows=sql_results[:top_n] if sql_results else [],
        debug=debug_info,
    )

    crud.add_message(
        session,
        conversation,
        role="assistant",
        content=followup_message,
        payload=response_payload.model_dump(),
    )

    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "conversation_id": conversation.id,
        "user_message": request.message,
        "plan": plan.model_dump() if plan else None,
        "sql_executed": plan.sql if plan else None,
        "sql_batch": batch_results,
        "sql_variables": gemini_payload.sql_variables,
        "sql_results": sql_results,
        "execution_summary": execution_summary.model_dump(),
        "assistant_message": followup_message,
        "top_n": top_n,
        "gemini": {
            "chat_prompt": getattr(gemini, "last_chat_prompt", None),
            "chat_response_text": getattr(gemini, "last_chat_response_text", None),
            "chat_response_payload": gemini_payload_raw,
            "answer_prompt": getattr(gemini, "last_answer_prompt", None),
            "answer_response_text": getattr(gemini, "last_answer_response_text", None),
            "answer_response_payload": followup_raw,
        },
        "debug": debug_info,
    }
    append_chat_log(log_entry)

    session.flush()

    return ChatResponse(
        conversation_id=conversation.id,
        assistant_message=followup_message,
        payload=response_payload,
    )


@app.get("/conversations/{conversation_id}", response_model=ConversationRead, tags=["chat"])
async def get_conversation(conversation_id: str, session: Session = Depends(get_session)):
    conversation = crud.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = [
        MessageRead(
            id=message.id,
            role=message.role,
            content=message.content,
            payload=MessagePayload(**(message.payload or {})) if message.payload else None,
            created_at=message.created_at,
        )
        for message in conversation.messages
    ]

    return ConversationRead(id=conversation.id, title=conversation.title, messages=messages)


def build_sql_summary(plan: SqlPlan, execution: SqlExecutionResult) -> str:
    if execution.row_count == 0:
        return "I ran the query but no matching records were found."

    first_row = execution.rows[0]
    if len(first_row) == 1:
        key, value = next(iter(first_row.items()))
        return f"The query `{plan.sql}` returned {value} for `{key}`."

    lines = ["Here are the first results:"]
    preview_rows = execution.rows[:3]
    for row in preview_rows:
        parts = [f"{col}: {val}" for col, val in row.items()]
        lines.append(" • " + ", ".join(parts))
    if execution.row_count > len(preview_rows):
        remaining = execution.row_count - len(preview_rows)
        lines.append(f"…and {remaining} more rows.")
    return "\n".join(lines)
