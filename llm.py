"""Deterministic stub that emulates Gemini structured responses."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class StructuredLLMResponse:
    reply: str
    sql: str
    enrichment_attributes: list[dict]


ATTRIBUTE_MAP = {
    "founder": "founder_bios",
    "founders": "founder_bios",
    "team size": "team_size",
    "headcount": "team_size",
    "funding": "funding_rounds",
    "revenue": "revenue_details",
    "location": "hq_location",
}


def normalise_attribute_name(name: str) -> str:
    """Convert an arbitrary attribute name into a snake_case column."""

    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_")
    return cleaned.lower() or "custom_attribute"


def detect_attribute(message: str) -> str | None:
    """Infer which startup attribute the user is requesting."""

    lowered = message.lower()
    for needle, column in ATTRIBUTE_MAP.items():
        if needle in lowered:
            return column
    if "attribute:" in lowered:
        custom = lowered.split("attribute:", 1)[1].strip()
        if custom:
            return normalise_attribute_name(custom)
    return None


def build_sql(limit: int, attribute: str | None) -> str:
    """Generate a simple SQL statement scoped to the startups table."""

    base_columns = ["id", "name", "description", "website"]
    if attribute and attribute not in base_columns:
        base_columns.append(attribute)
    columns_sql = ", ".join(base_columns)
    return f"SELECT {columns_sql} FROM startups ORDER BY created_at DESC LIMIT {limit};"


def generate_structured_response(message: str, result_limit: int = 10) -> StructuredLLMResponse:
    """Return a deterministic structured response that mirrors LLM output."""

    attribute = detect_attribute(message)
    sql = build_sql(result_limit, attribute)
    if attribute:
        reply = (
            "I will pull the latest startup records and queue enrichment for the "
            f"`{attribute}` attribute."
        )
        enrichment = [{"attribute_name": attribute, "reason": "requested_in_chat"}]
    else:
        reply = "Here are the latest startup records. Let me know if you need extra attributes."
        enrichment = []

    return StructuredLLMResponse(reply=reply, sql=sql, enrichment_attributes=enrichment)
