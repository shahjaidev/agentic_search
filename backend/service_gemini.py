"""Wrapper around Gemini 2.5 Flash responses for SQL planning."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import google.generativeai as genai

from backend.config import settings
from backend.schemas import SqlPlan

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKET_CATEGORIZATION_PATH = PROJECT_ROOT / "polymarket" / "market_categorization.md"

try:
    TAXONOMY_REFERENCE = MARKET_CATEGORIZATION_PATH.read_text(encoding="utf-8")
except OSError:  # pragma: no cover - defensive in case file missing
    TAXONOMY_REFERENCE = ""

SYSTEM_INSTRUCTION = f"""
You are a data assistant working with a SQLite table named polymarket_markets_enriched. You help craft precise SQL and concise explanations for users exploring Polymarket data, including pricing and liquidity insights.

Taxonomy reference for market categorization:
{TAXONOMY_REFERENCE or '(taxonomy reference unavailable)'}

Core guidance:
- Prefer generating a SQL SELECT statement that answers the user whenever the existing columns allow it.
- Use aggregations such as COUNT(*), SUM(...), AVG(...), MIN(...), and MAX(...) when they clarify the answer.
- Pricing columns include last_trade_price, best_bid, best_ask, and outcome_prices; liquidity metrics include liquidity_num (total), liquidity_amm, liquidity_clob, and volume_num. Use them directly to answer questions about spreads, depth, recent trading activity, or top markets by liquidity.
- When a user mentions entities, countries, tickers, or names (e.g., "Russia", "Putin", "Ethereum"), add case-insensitive filters on `question`, `description`, `market_slug`, and `tags` using those keywords before applying broader category filters. Prioritize markets that explicitly reference those terms.
- For multi-keyword prompts ("Microsoft" and "OpenAI"), include all keywords in the WHERE clause. Use grouped conditions like `(LOWER(question) LIKE '%microsoft%' OR LOWER(description) LIKE '%microsoft%' OR LOWER(tags) LIKE '%microsoft%')` combined with `OR` for each entity, and add acquisition-related keywords when relevant (`LIKE '%acquire%'`, `'%acquisition%'`).
- Combine keyword filters with relevant taxonomy levels (market_category*, market_category_*_name) so results stay on-topic (e.g., `market_category_l1_name = 'Politics' AND LOWER(question) LIKE '%russia%'`).
- Only skip SQL when the request cannot be satisfied; in those cases, leave `sql` empty and request enrichment via `enrichment_hint`.
- Suggest additional columns only when they would genuinely improve the result.
- Keep results limited to active markets by ensuring `end_date_iso > DATE('now')` whenever that column is involved, and cap row counts at 30 or fewer.
- Treat executed SQL results as the authoritative source; summarize them first, then optionally add complementary context using other future-dated market names that match the user’s intent.
- For references to specific markets, map them into the taxonomy levels (market_category, market_category_l1, market_category_l2, market_category_l3) and combine category matching with case-insensitive keyword filters on question/description fields.
- You may request multiple SQL statements by returning `sql_batch` (array of objects with optional `name`, required `sql`, and optional `sql_variables`). Statements execute sequentially and their outputs will be returned to you.
- Always set `top_n` to the number of markets you want to highlight (default 10, maximum 100).
- After execution you must populate `final_table_rows` with exactly `top_n` dictionaries representing the markets you want displayed. Ensure the dictionaries include consistent column keys.
- Always return valid JSON with keys: assistant_message, facts, suggested_sql_columns, enrichment_hint, sql, sql_variables, sql_batch, top_n, final_table_rows.

Example SQL patterns you can emit:
- Top liquidity today: `SELECT question, liquidity_num, last_trade_price FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') ORDER BY liquidity_num DESC LIMIT 5`
- Narrowest spread: `SELECT question, best_bid, best_ask, (best_ask - best_bid) AS spread FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') AND best_bid IS NOT NULL AND best_ask IS NOT NULL ORDER BY spread ASC LIMIT 5`
- Russia-focused request: `SELECT question, liquidity_num, last_trade_price, market_category_l1_name FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') AND (LOWER(question) LIKE '%russia%' OR LOWER(description) LIKE '%russia%' OR LOWER(tags) LIKE '%russia%') ORDER BY liquidity_num DESC LIMIT 5`
- Microsoft + OpenAI acquisition: `SELECT question, liquidity_num, last_trade_price FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') AND ((LOWER(question) LIKE '%microsoft%' OR LOWER(description) LIKE '%microsoft%' OR LOWER(tags) LIKE '%microsoft%') OR (LOWER(question) LIKE '%openai%' OR LOWER(description) LIKE '%openai%' OR LOWER(tags) LIKE '%openai%')) AND (LOWER(question) LIKE '%acquir%' OR LOWER(description) LIKE '%acquir%') ORDER BY liquidity_num DESC LIMIT 10`
"""

PROMPT_TEMPLATE = """
Available columns: {columns}
Recent conversation turns:
{history}

User question:
{user_question}
\n+Instructions:
- Analyze every executed query (see `batch_results` inside the additional context when present).
- Select the best markets and fill `final_table_rows` with exactly `top_n` entries.
- Return JSON following the standard schema.
"""

RESULT_TEMPLATE = """
Executed SQL statement:
{sql}

Result rows (JSON):
{rows}

Additional context:
{context}

Chat history (most recent first):
{history}

User question:
{user_question}
"""


class GeminiClient:
    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        self.api_key = (api_key or settings.gemini_api_key).strip()
        self.model_name = model_name or settings.gemini_model
        self.enabled = bool(self.api_key)
        self.logger = logging.getLogger(__name__)
        self.last_chat_prompt: Optional[str] = None
        self.last_chat_response_text: Optional[str] = None
        self.last_answer_prompt: Optional[str] = None
        self.last_answer_response_text: Optional[str] = None

        if self.enabled:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=SYSTEM_INSTRUCTION,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.8,
                    "response_mime_type": "application/json",
                },
            )
        else:
            self.model = None

    def run_chat(self, columns: List[str], user_message: str, history: List[Dict[str, str]] | None = None) -> Dict[str, Any]:
        formatted_history_lines = []
        for item in history or []:
            role = item.get("role", "assistant")
            content = item.get("content", "")
            formatted_history_lines.append(f"- {role}: {content}")
        formatted_history = "\n".join(formatted_history_lines)
        prompt = PROMPT_TEMPLATE.format(
            columns=", ".join(columns),
            history=formatted_history or "(no prior messages)",
            user_question=user_message,
        )
        self.last_chat_prompt = prompt

        if not self.enabled or self.model is None:
            fallback = self._fallback_response(user_message, columns)
            self.last_chat_response_text = json.dumps(fallback)
            return fallback

        try:
            response = self.model.generate_content(prompt)
            self.last_chat_response_text = getattr(response, "text", None)
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.logger.error("Gemini call failed: %s", exc)
            fallback = self._fallback_response(user_message, columns)
            self.last_chat_response_text = json.dumps(fallback)
            return fallback

        parsed = self._parse_response(response, user_message, columns)
        if self.last_chat_response_text is None:
            self.last_chat_response_text = json.dumps(parsed)
        return parsed

    def run_answer_with_results(
        self,
        user_message: str,
        sql: str,
        rows: List[Dict[str, Any]],
        context: Dict[str, Any] | None = None,
        history: List[Dict[str, str]] | None = None,
    ) -> Dict[str, Any]:
        context = context or {}
        formatted_history_lines = []
        for item in history or []:
            role = item.get("role", "assistant")
            content = item.get("content", "")
            formatted_history_lines.append(f"- {role}: {content}")
        formatted_history = "\n".join(formatted_history_lines)
        prompt = RESULT_TEMPLATE.format(
            sql=sql,
            rows=json.dumps(rows, indent=2),
            context=json.dumps(context, indent=2),
            history=formatted_history or "(no prior messages)",
            user_question=user_message,
        )
        self.last_answer_prompt = prompt

        if not self.enabled or self.model is None:
            summary = self._summarize_rows(sql, rows)
            fallback = {
                "answer": summary,
                "facts": [],
                "suggested_sql_columns": [],
                "enrichment_hint": None,
                "sql": sql,
                "sql_variables": {},
                "final_table_rows": rows[: context.get("top_n", 10)],
                "top_n": context.get("top_n", 10),
            }
            self.last_answer_response_text = json.dumps(fallback)
            return fallback
        try:
            response = self.model.generate_content(prompt)
            self.last_answer_response_text = getattr(response, "text", None)
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.logger.error("Gemini follow-up call failed: %s", exc)
            summary = self._summarize_rows(sql, rows)
            fallback = {
                "answer": summary,
                "facts": [],
                "suggested_sql_columns": [],
                "enrichment_hint": None,
                "sql": sql,
                "sql_variables": {},
                "final_table_rows": rows[: context.get("top_n", 10)],
                "top_n": context.get("top_n", 10),
            }
            self.last_answer_response_text = json.dumps(fallback)
            return fallback

        parsed = self._parse_response(response, user_message, [], allow_empty=True)
        if not parsed.get("assistant_message") and not parsed.get("answer"):
            summary = self._summarize_rows(sql, rows)
            parsed["answer"] = summary
        if self.last_answer_response_text is None:
            self.last_answer_response_text = json.dumps(parsed)
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
