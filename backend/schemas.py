"""Pydantic models that define request and response schemas for the API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class MessagePayload(BaseModel):
    facts: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_sql_columns: List[str] = Field(default_factory=list)
    enrichment_hint: Optional[Dict[str, Any]] = None
    sql: Optional[str] = None
    sql_rows: List[Dict[str, Any]] = Field(default_factory=list)
    sql_summary: Optional[str] = None
    sql_batch: List[Dict[str, Any]] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=100)
    final_table_rows: List[Dict[str, Any]] = Field(default_factory=list)
    debug: Dict[str, Any] = Field(default_factory=dict)


class SqlBatchItem(BaseModel):
    name: Optional[str] = None
    sql: str
    sql_variables: Dict[str, Any] = Field(default_factory=dict)


class GeminiResponse(BaseModel):
    answer: Optional[str] = None
    assistant_message: str = Field(default="", description="Plain-text assistant reply")
    facts: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_sql_columns: List[str] = Field(default_factory=list)
    enrichment_hint: Optional[Dict[str, Any]] = None
    sql: Optional[str] = None
    sql_variables: Dict[str, Any] = Field(default_factory=dict)
    sql_batch: List[SqlBatchItem] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=100)
    final_table_rows: List[Dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def coerce(cls, payload: Dict[str, Any], require_message: bool = True) -> "GeminiResponse":
        payload = payload or {}
        if payload.get("answer") and not payload.get("assistant_message"):
            payload["assistant_message"] = payload.get("answer", "")
        if not isinstance(payload.get("sql_variables"), dict):
            payload["sql_variables"] = {}
        if payload.get("sql_batch") is None:
            payload["sql_batch"] = []
        if "sql_batch" in payload and isinstance(payload["sql_batch"], list):
            normalized_batch = []
            for item in payload["sql_batch"]:
                if isinstance(item, dict) and "sql" in item:
                    normalized_batch.append(item)
            payload["sql_batch"] = normalized_batch
        if not isinstance(payload.get("final_table_rows"), list):
            payload["final_table_rows"] = []
        if payload.get("enrichment_hint") is not None and not isinstance(payload.get("enrichment_hint"), dict):
            payload["enrichment_hint"] = None
        if not isinstance(payload.get("facts"), list):
            payload["facts"] = []
        else:
            normalized_facts: list[dict[str, Any]] = []
            for fact in payload["facts"]:
                if isinstance(fact, dict):
                    normalized_facts.append(fact)
                elif isinstance(fact, str):
                    normalized_facts.append({"text": fact})
            payload["facts"] = normalized_facts
        model = cls.model_validate(payload)
        if require_message and not (model.answer or model.assistant_message):
            raise ValueError("Gemini response missing required `answer` field")
        return model

    def final_message(self) -> str:
        return (self.answer or self.assistant_message or "").strip()


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = Field(default=None, description="Existing conversation identifier.")
    message: str = Field(..., min_length=1, description="Latest user message content")


class ChatResponse(BaseModel):
    conversation_id: str
    assistant_message: str
    payload: MessagePayload


class MessageRead(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    payload: Optional[MessagePayload] = None
    created_at: datetime


class ConversationRead(BaseModel):
    id: str
    title: Optional[str] = None
    messages: List[MessageRead]


class SqlPlan(BaseModel):
    sql: str
    columns_considered: List[str]
    missing_columns: List[str]
    suggested_columns: List[str] = Field(default_factory=list)

    @field_validator("sql")
    @classmethod
    def ensure_select(cls, value: str) -> str:
        normalized = value.lower().strip()
        if not normalized.startswith("select") and not normalized.startswith("with"):
            raise ValueError("Only SELECT statements are allowed in demo mode")
        return value


class EnrichmentAction(BaseModel):
    attribute: str
    reason: str


class AgentDebugPayload(BaseModel):
    sql_plan: SqlPlan
    enrichment_actions: List[EnrichmentAction] = Field(default_factory=list)
    sql_results_preview: List[Dict[str, Any]] = Field(default_factory=list)


class SqlExecutionResult(BaseModel):
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    preview_columns: List[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    assistant_message: str
    facts: List[Dict[str, Any]] = Field(default_factory=list)
    plan: Optional[SqlPlan] = None
    sql_results: SqlExecutionResult = Field(default_factory=SqlExecutionResult)
    enrichment_actions: List[EnrichmentAction] = Field(default_factory=list)
    suggested_sql_columns: List[str] = Field(default_factory=list)
