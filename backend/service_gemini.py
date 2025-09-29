"""Wrapper around Gemini 2.5 Flash responses for SQL planning."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import google.generativeai as genai

from backend.config import settings
from backend.schemas import SqlPlan

PROMPT_TEMPLATE = """
You are a data assistant working with a SQLite table named yc_companies.
Columns available: {columns}
Recent conversation turns:
{history}

When answering the user, you must:
- Produce a SQL SELECT statement that will answer the user's question whenever it is possible with the available columns.
- Carefully consider if the question can be answered with the current columns and aggregations such as COUNT(*), SUM(...), AVG(...), MIN(...), and MAX(...) etc. when they can help answer the question.
- Only omit SQL as a last resort if the question cannot be answered with the current columns and aggregations or other sql operations; in that case, set sql to an empty string and recommend enrichment.
- Suggest additional columns in suggested_sql_columns only if they would truly help.
- If enrichment is needed, explicitly set enrichment_hint with the column name and reason.

Return JSON with keys:
- assistant_message: conversational answer (string)
- facts: array of objects with 'text' and 'source' (may be empty)
- suggested_sql_columns: array of useful column names to display in the UI
- enrichment_hint: optional object with 'attribute' and 'reason' if data is missing
- sql: SQL SELECT statement using available columns to answer the question if possible
- sql_variables: dictionary of parameters to plug into the SQL query (optional)

Example 1:
User question: "Which is the largest batch of YC, and how many companies are in each industry in this batch?"
SQL to run:
WITH batch_counts AS (
    SELECT batch, COUNT(*) AS company_count
    FROM yc_companies
    GROUP BY batch
    ORDER BY company_count DESC
    LIMIT 1
)
SELECT c.industry, COUNT(*) AS companies_in_industry
FROM yc_companies c
JOIN batch_counts bc ON c.batch = bc.batch
GROUP BY c.industry
ORDER BY companies_in_industry DESC;

Example 2:
User question: "Find all companies in the Virtual or Augmented Reality space that raised money in 2025 and are hiring."
SQL to run:
SELECT name, industries, isHiring, latest_fundraising_date
FROM yc_companies
WHERE isHiring = 1
  AND latest_fundraising_date LIKE '2025%'
  AND (
        industries LIKE '%Virtual Reality%'
        OR industries LIKE '%Augmented Reality%'
        OR long_description LIKE '%virtual reality%'
        OR long_description LIKE '%augmented reality%'
        OR one_liner LIKE '%virtual reality%'
        OR one_liner LIKE '%augmented reality%'
      );

Example 3:
User question: "What is the average latest fundraising amount for Summer 2025 companies vs Winter 2025 companies?"
SQL to run:
SELECT batch, AVG(CAST(latest_fundraising_amount AS REAL)) AS avg_latest_fundraising
FROM yc_companies
WHERE latest_fundraising_amount IS NOT NULL
  AND batch IN ('Summer 2025', 'Winter 2025')
GROUP BY batch;

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
        prompt = PROMPT_TEMPLATE.format(columns=", ".join(columns), history=formatted_history or "(no prior messages)")
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


