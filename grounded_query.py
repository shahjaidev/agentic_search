#!/usr/bin/env python3
"""Minimal grounded lookup that returns a JSON array of companies."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable

from google import genai
from google.genai import types

from database import ensure_startup_attribute, upsert_startup, update_startup_attribute

def _join_candidate_text(response: Any) -> str:
    """Collect any text fragments from the model response candidates."""

    fragments: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                fragments.append(text)
    return "\n".join(fragment.strip() for fragment in fragments if fragment).strip()


MODEL_NAME = "gemini-2.5-flash-lite"
DEFAULT_QUERY = "20 companies in sf focusing on deeptech started after 2023"
OUTPUT_PATH = Path(__file__).with_name("grounded_query_runs.jsonl")


def load_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Set GOOGLE_API_KEY (preferred) or GEMINI_API_KEY in your environment.")
    return key.strip()


def build_prompt(user_query: str) -> str:
    template = {
        "query": user_query,
        "summary": "",
        "facts": [
            {"text": "", "source": ""}
        ],
        "companies": [
            {
                "name": "",
                "description": "",
                "headquarters": "",
                "founding_year": "",
                "focus_areas": ["replace_me"],
                "funding_stage": "replace_me",
                "total_funding_usd": "replace_me",
                "website": "https://replace.me",
                "founders": ["replace_me"],
                "key_highlights": ["Replace this with a grounded highlight or explain missing data"],
                "sources": ["https://replace.me/source"],
                "populated_fields": [
                    "headquarters",
                    "focus_areas",
                    "founders",
                    "website",
                    "funding_stage",
                    "total_funding_usd"
                ]
            }
        ],
        "suggested_sql_columns": [
            "company_name",
            "founding_year",
            "focus_areas",
            "funding_stage",
            "website"
        ]
    }
    return (
        "You ground every fact with Google Search results.\n"
        "Fill out the following JSON template with real data.\n"
        "- Provide at least 30 San Francisco/Bay Area robotics startups founded after 2023.\n"
        "- Keep the same keys as the template.\n"
        "- For each company, exhaust grounded web searches to populate headquarters, focus_areas, founders, website, funding_stage, and total_funding_usd; do not leave these empty unless you cannot verify them after multiple sources.\n"
        "- Every company must include at least one HTTPS source URL (no citation numbers like [3]).\n"
        "- Cite the canonical publisher or company URL directly (e.g. https://example.com/article); never use Google or vertexaisearch redirect links.\n"
        "- Populate `populated_fields` ONLY with whichever of {headquarters, focus_areas, founders, website, funding_stage, total_funding_usd} you verified for that company.\n"
        "- Do not include literal \\n escape sequences inside string values; write sentences plainly.\n"
        "Return ONLY valid JSON.\n"
        f"Template: {json.dumps(template)}"
    )


def _serialise_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _safe_attribute_name(name: str) -> str | None:
    if not name:
        return None
    if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
        return name
    return None


def ingest_companies(companies: Iterable[Dict[str, Any]]) -> None:
    for company in companies or []:
        name = company.get("name")
        if not name:
            continue
        description = company.get("description") or None
        website = company.get("website") or None
        startup = upsert_startup(name=name, description=description, website=website)
        populated = set(company.get("populated_fields", []) or [])
        populated.update({"key_highlights", "sources"})
        for attribute in populated:
            attr_name = _safe_attribute_name(attribute)
            if not attr_name or attr_name in {"name", "description", "website"}:
                continue
            value = company.get(attr_name)
            if value in (None, "", [], {}):
                continue
            ensure_startup_attribute(attr_name)
            update_startup_attribute(startup.id, attr_name, _serialise_value(value))


def request_grounded_json(user_query: str) -> Dict[str, Any]:
    client = genai.Client(api_key=load_api_key())
    grounding_tool = types.Tool(google_search=types.GoogleSearch())

    config = types.GenerateContentConfig(
        tools=[grounding_tool],
        temperature=0,
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=build_prompt(user_query),
        config=config,
    )

    payload = (getattr(response, "text", "") or "").strip()
    if not payload:
        payload = _join_candidate_text(response)
    if not payload:
        return {"query": user_query, "summary": "", "facts": [], "companies": [], "suggested_sql_columns": []}

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {"query": user_query, "summary": payload, "facts": [], "companies": [], "suggested_sql_columns": []}

    return data


def append_jsonl(record: Dict[str, Any]) -> None:
    with open(OUTPUT_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True))
        handle.write("\n")


def main() -> None:
    user_query = " ".join(sys.argv[1:]).strip() or DEFAULT_QUERY
    if len(sys.argv) < 2:
        print(f"No query provided. Falling back to default: '{DEFAULT_QUERY}'.", file=sys.stderr)

    result = request_grounded_json(user_query)
    try:
        ingest_companies(result.get("companies", []))
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Warning: failed to ingest companies: {exc}", file=sys.stderr)
    print(json.dumps(result, indent=2, sort_keys=True))
    append_jsonl({"query": user_query, "result": result})


if __name__ == "__main__":
    main()
