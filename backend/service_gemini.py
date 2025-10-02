"""Wrapper around Gemini 2.5 Flash responses for SQL planning."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import google.genai
import google.generativeai as genai
from opik import configure
from opik.integrations.genai import track_genai

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
- When direct keyword hits are sparse, reason about adjacent concepts and add related keywords or category filters (e.g., a GPU shortage can affect AI model releases, data centers, cryptocurrency mining). Blend explicit keyword matching with relevant taxonomy levels (`market_category_*_name`) so the result set includes both direct and indirect markets.
- For multi-keyword prompts ("Microsoft" and "OpenAI"), include all keywords in the WHERE clause. Use grouped conditions like `(LOWER(question) LIKE '%microsoft%' OR LOWER(description) LIKE '%microsoft%' OR LOWER(tags) LIKE '%microsoft%')` combined with `OR` for each entity, and add acquisition-related keywords when relevant (`LIKE '%acquire%'`, `'%acquisition%'`).
- Combine keyword filters with relevant taxonomy levels (market_category*, market_category_*_name) so results stay on-topic (e.g., `market_category_l1_name = 'Politics' AND LOWER(question) LIKE '%russia%'`).
- Only skip SQL when the request cannot be satisfied; in those cases, leave `sql` empty and request enrichment via `enrichment_hint`.
- Suggest additional columns only when they would genuinely improve the result.
- Keep results limited to active markets by ensuring `end_date_iso > DATE('now')` whenever that column is involved, and cap row counts at 30 or fewer.
- Treat executed SQL results as the authoritative source; summarize them first, then optionally add complementary context using other future-dated market names that match the user's intent.
- For references to specific markets, map them into the taxonomy levels (market_category, market_category_l1, market_category_l2, market_category_l3) and combine category matching with case-insensitive keyword filters on question/description fields.
- You may request multiple SQL statements by returning `sql_batch` (array of objects with optional `name`, required `sql`, and optional `sql_variables`). Statements execute sequentially and their outputs will be returned to you.
- Always set `top_n` to the number of markets you want to highlight (default 10, maximum 100).
- After execution you must populate `final_table_rows` with exactly `top_n` dictionaries representing the markets you want displayed. Ensure the dictionaries include consistent column keys.
- Always return valid JSON with keys: assistant_message, facts, suggested_sql_columns, enrichment_hint, sql, sql_variables, sql_batch, top_n, final_table_rows.
- When prompts ask which markets are "affected", "impacted", "related", or "about" a given event or entity, retrieve a SELECT result set with at least 15–25 candidate markets (use `LIMIT 25`) that includes question text, liquidity_num, last_trade_price, end_date_iso, and taxonomy levels, then choose the strongest ones for `final_table_rows`.

Semantic Search Integration:
- When additional context is provided via `semantic_search_results`, use these semantically relevant markets to enhance your understanding of the user's query.
- These markets are found using vector similarity search and may include markets that don't match exact keyword filters but are semantically related to the user's question.
- Incorporate insights from semantic search results into your answer when they provide valuable context, even if they don't appear in the SQL results.
- Use semantic search results to suggest related markets or provide broader context about market trends and themes.

Example SQL patterns you can emit:
- Top liquidity today: `SELECT question, liquidity_num, last_trade_price FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') ORDER BY liquidity_num DESC LIMIT 5`
- Narrowest spread: `SELECT question, best_bid, best_ask, (best_ask - best_bid) AS spread FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') AND best_bid IS NOT NULL AND best_ask IS NOT NULL ORDER BY spread ASC LIMIT 5`
- Russia-focused request: `SELECT question, liquidity_num, last_trade_price, market_category_l1_name FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') AND (LOWER(question) LIKE '%russia%' OR LOWER(description) LIKE '%russia%' OR LOWER(tags) LIKE '%russia%') ORDER BY liquidity_num DESC LIMIT 5`
- Microsoft + OpenAI acquisition: `SELECT question, liquidity_num, last_trade_price FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') AND ((LOWER(question) LIKE '%microsoft%' OR LOWER(description) LIKE '%microsoft%' OR LOWER(tags) LIKE '%microsoft%') OR (LOWER(question) LIKE '%openai%' OR LOWER(description) LIKE '%openai%' OR LOWER(tags) LIKE '%openai%')) AND (LOWER(question) LIKE '%acquir%' OR LOWER(description) LIKE '%acquir%') ORDER BY liquidity_num DESC LIMIT 10`
- Event impact prompt: `SELECT question, liquidity_num, last_trade_price, end_date_iso, market_category_l1_name FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') AND (LOWER(question) LIKE '%openai%' OR LOWER(description) LIKE '%openai%') AND (LOWER(question) LIKE '%launch%' OR LOWER(description) LIKE '%launch%') ORDER BY liquidity_num DESC LIMIT 25`
- Derived impact example: `SELECT question, liquidity_num, last_trade_price, end_date_iso, market_category_l1_name FROM polymarket_markets_enriched WHERE end_date_iso > DATE('now') AND (LOWER(question) LIKE '%gpu%' OR LOWER(description) LIKE '%gpu%' OR LOWER(tags) LIKE '%gpu%' OR market_category_l2_name LIKE '%Artificial Intelligence%' OR market_category_l2_name LIKE '%Semiconductor%') AND (LOWER(question) LIKE '%shortage%' OR LOWER(description) LIKE '%shortage%' OR LOWER(question) LIKE '%supply%' OR LOWER(description) LIKE '%supply%') ORDER BY liquidity_num DESC LIMIT 25`
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

Semantic search results (if available):
{semantic_context}

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

        # Configure Opik if API key is available
        if settings.opik_api_key:
            # Set project name in environment for Opik to pick up
            import os
            if settings.opik_project:
                os.environ["OPIK_PROJECT_NAME"] = settings.opik_project
            configure(api_key=settings.opik_api_key, workspace=settings.opik_workspace or "shahjaidev")

        if self.enabled:
            # Use both the old genai client for backward compatibility and new google.genai for Opik
            genai.configure(api_key=self.api_key)
            
            # Create new google.genai client with Opik tracking
            self.genai_client = google.genai.Client(api_key=self.api_key)
            if settings.opik_api_key:
                self.tracked_client = track_genai(self.genai_client)
            else:
                self.tracked_client = self.genai_client
            
            # Keep the old model for backward compatibility
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
            self.genai_client = None
            self.tracked_client = None

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
            # Always use the old model for now since Opik integration may be causing issues
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
        
        # Format semantic search results
        semantic_results = context.get("semantic_search_results", [])
        semantic_context = ""
        if semantic_results:
            semantic_context = f"Found {len(semantic_results)} semantically relevant markets:\n"
            for i, market in enumerate(semantic_results[:3], 1):  # Show top 3
                semantic_context += f"{i}. {market.get('question', 'N/A')}\n"
                semantic_context += f"   Category: {market.get('market_category_name', 'N/A')}\n"
                semantic_context += f"   Relevance: {market.get('relevance_score', 'N/A'):.3f}\n"
                if market.get('description'):
                    desc = market['description'][:100] + "..." if len(market['description']) > 100 else market['description']
                    semantic_context += f"   Description: {desc}\n"
                semantic_context += "\n"
        
        prompt = RESULT_TEMPLATE.format(
            sql=sql,
            rows=json.dumps(rows, indent=2),
            context=json.dumps(context, indent=2),
            semantic_context=semantic_context,
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
            # Use the tracked client if Opik is configured, otherwise fall back to the old model
            if self.tracked_client and settings.opik_api_key:
                # Convert model name format for google.genai client
                model_name = self.model_name.replace("models/", "") if self.model_name.startswith("models/") else self.model_name
                response = self.tracked_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "temperature": 0.1,
                        "top_p": 0.8,
                        "response_mime_type": "application/json",
                    }
                )
                self.last_answer_response_text = getattr(response, "text", None)
            else:
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

        assistant_message = parsed.get("assistant_message")
        if not assistant_message:
            if parsed.get("answer"):
                parsed["assistant_message"] = parsed.get("answer", "")
            elif parsed.get("sql") or parsed.get("sql_batch") or allow_empty:
                truncated = user_message.strip().replace("\n", " ")[:120]
                parsed["assistant_message"] = (
                    f"Generated SQL plan for '{truncated}'" if truncated else "Generated SQL plan."
                )
            else:
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
