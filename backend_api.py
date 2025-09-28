"""FastAPI application exposing chat endpoints for the agentic search system."""
from __future__ import annotations

from typing import Any, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import (
    ENGINE,
    add_chat_message,
    enqueue_enrichment_job,
    init_db,
    list_chat_messages,
    record_sql_execution,
    upsert_startup,
)
from llm import generate_structured_response


app = FastAPI(title="Agentic Search API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to send to the assistant.")
    result_limit: int = Field(10, ge=1, le=200, description="Maximum rows to return.")


class EnrichmentHint(BaseModel):
    attribute_name: str
    reason: str


class ChatResponse(BaseModel):
    reply: str
    sql: str
    sql_results: List[dict[str, Any]]
    enrichment_attributes: List[EnrichmentHint]


class ChatHistoryResponse(BaseModel):
    messages: List[dict[str, Any]]


@app.on_event("startup")
def on_startup() -> None:
    """Initialise the database and seed demo data."""

    init_db()
    seed_demo_data()


@app.get("/healthz", tags=["system"])
def healthcheck() -> dict[str, str]:
    """Simple health probe."""

    return {"status": "ok"}


@app.get("/chat/history", response_model=ChatHistoryResponse, tags=["chat"])
def chat_history(limit: int = 20) -> ChatHistoryResponse:
    """Return previous chat messages for the UI."""

    messages = [
        {
            "id": msg.id,
            "user_message": msg.user_message,
            "assistant_message": msg.assistant_message,
            "created_at": msg.created_at.isoformat(),
            "structured_response": msg.structured_response,
        }
        for msg in list_chat_messages(limit=limit)
    ]
    return ChatHistoryResponse(messages=messages)


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
def handle_chat(request: ChatRequest) -> ChatResponse:
    """Process a user chat turn."""

    structured = generate_structured_response(request.message, request.result_limit)
    sql_results = execute_sql(structured.sql)
    for hint in structured.enrichment_attributes:
        enqueue_enrichment_job(hint["attribute_name"], payload={"source": hint["reason"]})
    add_chat_message(
        user_message=request.message,
        assistant_message=structured.reply,
        structured_response={
            "reply": structured.reply,
            "sql": structured.sql,
            "enrichment_attributes": structured.enrichment_attributes,
        },
    )
    response = ChatResponse(
        reply=structured.reply,
        sql=structured.sql,
        sql_results=sql_results,
        enrichment_attributes=[
            EnrichmentHint(**hint) for hint in structured.enrichment_attributes
        ],
    )
    return response


def execute_sql(sql_statement: str) -> List[dict[str, Any]]:
    """Execute a read-only SQL statement and return rows as dicts."""

    if not sql_statement.lower().strip().startswith("select"):
        raise HTTPException(status_code=400, detail="Only SELECT statements are allowed.")

    with ENGINE.begin() as connection:
        result = connection.execute(text(sql_statement))
        rows = [dict(row._mapping) for row in result]
    record_sql_execution(sql_statement)
    return rows


def seed_demo_data() -> None:
    """Ensure a few startup rows exist so the UI has content."""

    demo_startups = [
        ("Parallel AI", "Enterprise research copilot", "https://parallel.ai"),
        ("Lantern Labs", "Data observability for AI", "https://lanternlabs.ai"),
        ("Orbit Analytics", "Spatial analytics platform", "https://orbitalytics.io"),
    ]
    for name, desc, url in demo_startups:
        upsert_startup(name=name, description=desc, website=url)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend_api:app", host="0.0.0.0", port=8000, reload=False)
