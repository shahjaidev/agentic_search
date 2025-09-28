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
    debug: Dict[str, Any] = Field(default_factory=dict)


class GeminiResponse(BaseModel):
    answer: Optional[str] = None
    assistant_message: str = Field(default="", description="Plain-text assistant reply")
    facts: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_sql_columns: List[str] = Field(default_factory=list)
    enrichment_hint: Optional[Dict[str, Any]] = None
    sql: Optional[str] = None
    sql_variables: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def coerce(cls, payload: Dict[str, Any], require_message: bool = True) -> "GeminiResponse":
        payload = payload or {}
        if payload.get("answer") and not payload.get("assistant_message"):
            payload["assistant_message"] = payload.get("answer", "")
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
        if not value.lower().strip().startswith("select"):
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


