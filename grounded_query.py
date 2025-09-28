"""Quick demo script for Gemini 2.5 Flash with Google Grounding.

Execute with:
    python grounded_query.py "What is the founder background of Stripe?"
If no query is passed, the script uses a default: "companies in sf focusing on deeptech started after 2023".
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

import google.generativeai as genai
from google.generativeai import protos  # for Tool / GoogleSearchRetrieval

MODEL_NAME = "models/gemini-2.5-flash"
DEFAULT_QUERY = "companies in sf focusing on deeptech started after 2023"


def load_api_key() -> str:
    try:
        return os.environ["GEMINI_API_KEY"].strip()
    except KeyError as exc:  # pragma: no cover
        raise RuntimeError("Set GEMINI_API_KEY in your environment.") from exc


def build_prompt(user_query: str) -> str:
    return (
        "You ground your answers with Google data. "
        "Summarize findings for the user query inside JSON with keys: "
        "`query`, `summary`, `facts` (array of fact objects with `text` and `source`), "
        "and `suggested_sql_columns` (array of strings describing column names). "
        "Stick to valid JSON without markdown or commentary. Query: "
        f"{user_query}"
    )


def request_grounded_json(user_query: str) -> Dict[str, Any]:
    genai.configure(api_key=load_api_key())

    # Enable Google Grounding (correct tool name: google_search_retrieval)
    tool = protos.Tool(google_search_retrieval=protos.GoogleSearchRetrieval())

    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        tools=[tool],
        generation_config={
            "temperature": 0,
            "top_p": 0.8,
            "response_mime_type": "application/json",
        },
    )

    # Generate and robustly coerce to JSON
    response = model.generate_content(build_prompt(user_query))

    # response.text should already be JSON because of response_mime_type
    payload_text = (response.text or "").strip()
    if not payload_text:
        return {"query": user_query, "summary": "", "facts": [], "suggested_sql_columns": []}

    try:
        return json.loads(payload_text)
    except json.JSONDecodeError:
        # Fallback: try to extract first JSON block from the candidate parts if any
        for cand in getattr(response, "candidates", []) or []:
            for part in getattr(cand.content, "parts", []) or []:
                if hasattr(part, "text"):
                    try:
                        return json.loads(part.text)
                    except json.JSONDecodeError:
                        continue
        # Last resort: wrap raw text
        return {
            "query": user_query,
            "summary": payload_text,
            "facts": [],
            "suggested_sql_columns": [],
        }


def main() -> None:
    user_query = " ".join(sys.argv[1:]).strip() or DEFAULT_QUERY
    if len(sys.argv) < 2:
        print(f"No query provided. Falling back to default: '{DEFAULT_QUERY}'.", file=sys.stderr)
    result = request_grounded_json(user_query)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
