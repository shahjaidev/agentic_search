"""Wrapper around Gemini 2.5 Flash responses for SQL planning."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import google.generativeai as genai

from backend.config import settings
from backend.schemas import SqlPlan

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKET_CATEGORIZATION_PATH = PROJECT_ROOT / "polymarket" / "market_categorization.md"

try:
    TAXONOMY_REFERENCE = MARKET_CATEGORIZATION_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover - defensive in case file missing
    TAXONOMY_REFERENCE = ""

PROMPT_TEMPLATE = """
You are a data assistant working with a SQLite table named polymarket_markets.
Columns available: {columns}
Recent conversation turns:
{history}

Taxonomy reference for market categorization:
{taxonomy}

When answering the user, you must:
- Produce a SQL SELECT statement that will answer the user's question whenever it is possible with the available columns.
- Carefully consider if the question can be answered with the current columns and aggregations such as COUNT(*), SUM(...), AVG(...), MIN(...), and MAX(...) etc. when they can help answer the question.
- Only omit SQL as a last resort if the question cannot be answered with the current columns and aggregations or other sql operations; in that case, set sql to an empty string and recommend enrichment.
- Suggest additional columns in suggested_sql_columns only if they would truly help.
- If enrichment is needed, explicitly set enrichment_hint with the column name and reason.
- When the user references a specific Polymarket market or question, identify the best matching category codes (market_category, market_category_l1, market_category_l2, market_category_l3) using the taxonomy above. Use those levels to find related markets by matching on the most specific available level (prefer L3, then L2, then L1).
- When the user references a specific Polymarket market or question, identify the best matching category codes (market_category, market_category_l1, market_category_l2, market_category_l3) using the taxonomy above. Use those levels to find related markets by matching on the most specific available level (prefer L3, then L2, then L1).
- Extract the key entity names, people, organizations, or events mentioned by the user (or contained in the anchor market) and include case-insensitive LIKE filters on question and description so returned markets explicitly reference those same entities. Combine category matching with these keyword filters to avoid unrelated results.
- Any SQL you generate must cap results to 30 rows or fewer using LIMIT 30 (or a smaller number when appropriate).

Return JSON with keys:
- assistant_message: conversational answer (string)
- facts: array of objects with 'text' and 'source' (may be empty)
- suggested_sql_columns: array of useful column names to display in the UI
- enrichment_hint: optional object with 'attribute' and 'reason' if data is missing
- sql: SQL SELECT statement using available columns to answer the question if possible
- sql_variables: dictionary of parameters to plug into the SQL query (optional)

Example 1:
User question: "I'm looking at the market 'Netanyahu out by 2025'. What other markets in the same detailed category should I compare it with?"
SQL to run:
SELECT market_id, question, end_date_iso, market_category, market_category_l1_name, market_category_l2_name, market_category_l3_name
FROM polymarket_markets
WHERE market_category_l3_name = 'Government Officials'
  AND market_id != 'netanyahu-out-in-2025-492'
  AND (
        LOWER(question) LIKE '%netanyahu%'
        OR LOWER(description) LIKE '%netanyahu%'
      )
ORDER BY end_date_iso
LIMIT 30;

Example 2:
User question: "List markets similar to the Fed rate cuts market." 
SQL to run:
SELECT market_id, question, rewards, end_date_iso
FROM polymarket_markets
WHERE market_category_l2_name = 'Interest Rates'
  AND (
        LOWER(question) LIKE '%fed%'
        OR LOWER(description) LIKE '%fed%'
        OR LOWER(question) LIKE '%federal reserve%'
        OR LOWER(description) LIKE '%federal reserve%'
      )
ORDER BY end_date_iso
LIMIT 30;

Example 3:
User question: "How many markets per primary category are currently accepting orders?"
SQL to run:
SELECT market_category_l1_name AS category, COUNT(*) AS markets_accepting_orders
FROM polymarket_markets
WHERE accepting_orders = 1
GROUP BY market_category_l1_name
ORDER BY markets_accepting_orders DESC;

Always return valid JSON.
"""

RESULT_TEMPLATE = """
You previously generated the SQL query shown below and it has now been executed.
SQL statement: {sql}
Rows (JSON): {rows}
Additional context: {context}
Chat history (most recent first):
{history}

Use this information to craft a conversational answer to the user's question. Reference the key figures explicitly and keep things concise. If context indicates pending_columns that are not yet available, acknowledge the enrichment request and explain that the answer will follow once those columns are populated. Respond with JSON following the same schema as before.
"""


class GeminiClient:
    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key = (api_key or settings.gemini_api_key).strip()
        self.model_name = model_name or settings.gemini_model
        self.enabled = bool(self.api_key)
        self.logger = logging.getLogger(__name__)

        if self.enabled:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.8,
                    "response_mime_type": "application/json",
                },
            )
        else:
            self.model = None

    def run_chat(self, columns: List[str], user_message: str, history: List[Dict[str, str]] | None = None) -> Dict[str, Any]:
        if not self.enabled or self.model is None:
            return self._fallback_response(user_message, columns)

        formatted_history_lines = []
        for item in history or []:
            role = item.get("role", "assistant")
            content = item.get("content", "")
            formatted_history_lines.append(f"- {role}: {content}")
        formatted_history = "\n".join(formatted_history_lines)
        prompt = PROMPT_TEMPLATE.format(
            columns=", ".join(columns),
            history=formatted_history or "(no prior messages)",
            taxonomy=TAXONOMY_REFERENCE or "(taxonomy reference unavailable)",
        )
        full_prompt = f"{prompt}\nUser question: {user_message}"

        try:
            response = self.model.generate_content(full_prompt)
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.logger.error("Gemini call failed: %s", exc)
            return self._fallback_response(user_message, columns)

        return self._parse_response(response, user_message, columns)

    def run_answer_with_results(
        self,
        user_message: str,
        sql: str,
        rows: List[Dict[str, Any]],
        context: Dict[str, Any] | None = None,
        history: List[Dict[str, str]] | None = None,
    ) -> Dict[str, Any]:
        if not self.enabled or self.model is None:
            summary = self._summarize_rows(sql, rows)
            return {
                "answer": summary,
                "facts": [],
                "suggested_sql_columns": [],
                "enrichment_hint": None,
                "sql": sql,
                "sql_variables": {},
            }

        context = context or {}
        formatted_history_lines = []
        for item in history or []:
            role = item.get("role", "assistant")
            content = item.get("content", "")
            formatted_history_lines.append(f"- {role}: {content}")
        formatted_history = "\n".join(formatted_history_lines)
        formatted_history_lines = []
        for item in history or []:
            role = item.get("role", "assistant")
            content = item.get("content", "")
            formatted_history_lines.append(f"- {role}: {content}")
        formatted_history = "\n".join(formatted_history_lines)
        prompt = RESULT_TEMPLATE.format(sql=sql, rows=json.dumps(rows, indent=2), context=json.dumps(context, indent=2), history=formatted_history or "(no prior messages)")
        full_prompt = f"{prompt}\nUser question: {user_message}"
        try:
            response = self.model.generate_content(full_prompt)
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.logger.error("Gemini follow-up call failed: %s", exc)
            summary = self._summarize_rows(sql, rows)
            return {
                "answer": summary,
                "facts": [],
                "suggested_sql_columns": [],
                "enrichment_hint": None,
                "sql": sql,
                "sql_variables": {},
            }

        parsed = self._parse_response(response, user_message, [], allow_empty=True)
        if not parsed.get("assistant_message") and not parsed.get("answer"):
            summary = self._summarize_rows(sql, rows)
            parsed["answer"] = summary
        return parsed

    def _parse_response(
        self,
        response: Any,
        user_message: str,
        columns: List[str],
        allow_empty: bool = False,
    ) -> Dict[str, Any]:
        payload_text = (getattr(response, "text", None) or "{}").strip()
        try:
            parsed = json.loads(payload_text or "{}")
        except json.JSONDecodeError:  # pragma: no cover
            self.logger.warning("Gemini returned non-JSON payload; using raw text fallback")
            parsed = {"assistant_message": payload_text}

        if isinstance(parsed, list):
            parsed = parsed[0] if parsed and isinstance(parsed[0], dict) else {"assistant_message": payload_text}

        if not isinstance(parsed, dict):
            parsed = {"assistant_message": str(parsed)}

        if not parsed.get("assistant_message") and not allow_empty:
            self.logger.warning("Gemini response missing assistant_message; using fallback")
            return self._fallback_response(user_message, columns)

        return parsed

    def _summarize_rows(self, sql: str, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "The query returned no results."
        first_row = rows[0]
        if len(first_row) == 1:
            key, value = next(iter(first_row.items()))
            return f"The query `{sql}` returned {value} for `{key}`."
        parts = [
            " • " + ", ".join(f"{col}: {val}" for col, val in row.items())
            for row in rows[:3]
        ]
        return "Here are the first results:\n" + "\n".join(parts)

    def _fallback_response(self, user_message: str, columns: List[str]) -> Dict[str, Any]:
        return {
            "answer": (
                "I'm using a demo dataset and couldn't reach Gemini. "
                "Please check the backend logs or provide the answer manually."
            ),
            "facts": [],
            "suggested_sql_columns": columns[:3],
            "enrichment_hint": None,
            "sql": "",
            "sql_variables": {},
        }


def get_gemini_client() -> GeminiClient:
    """Convenience accessor for dependency injection."""

    return GeminiClient()
