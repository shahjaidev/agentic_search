#!/usr/bin/env python3
"""Batch categorize Polymarket markets using Gemini with server-side context caching.

This script reads market rows from an SQLite database, groups them into
batches, requests category codes from Gemini, logs the responses to JSONL,
and writes the resulting code into a `market_category` column.

Now uses Gemini API **explicit context caching** to cache the taxonomy +
system instruction on the server, removing the need for local KV caching.

Usage::

    python polymarket_categorize_batch.py \
        --db data/polymarket_markets.db \
        --jsonl-out data/polymarket_market_categories.jsonl \
        --cache-ttl-seconds 1800

Environment::

    export GOOGLE_API_KEY=...  # or GEMINI_API_KEY
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from google import genai
from google.genai import types

# IMPORTANT: explicit caching requires a concrete version suffix (e.g., "-001")
# and is supported on most 2.x models. See: https://ai.google.dev/gemini-api/docs/caching
MODEL_NAME = "models/gemini-2.5-flash-lite"

DEFAULT_BATCH_SIZE = 32
DEFAULT_JSONL_LOG = Path("/Users/jaidevshah/agentic_search/data/polymarket_market_categories.jsonl")
DEFAULT_DB_PATH = Path("/Users/jaidevshah/agentic_search/data/polymarket_markets.db")
CATEGORY_REFERENCE_PATH = Path("/Users/jaidevshah/agentic_search/polymarket/market_categorization.md")

CATEGORY_NAME_MAP: Dict[str, str] = {
    "1": "Sports",
    "1.1": "American Football (NFL)",
    "1.1.1": "Game Outcome",
    "1.1.2": "Championship",
    "1.1.3": "Player Props",
    "1.1.4": "Game Props",
    "1.1.5": "Draft",
    "1.2": "Basketball (NBA)",
    "1.2.1": "Game Outcome",
    "1.2.2": "Championship",
    "1.2.3": "Player Awards & Milestones",
    "1.2.4": "All-Star Events",
    "1.3": "Soccer",
    "1.3.1": "Club Football",
    "1.3.2": "International Football",
    "1.4": "Baseball (MLB)",
    "1.4.1": "Game Outcome",
    "1.4.2": "League Structure",
    "1.5": "Combat Sports",
    "1.5.1": "UFC",
    "1.5.2": "Boxing",
    "1.6": "Tennis",
    "1.6.1": "Match Outcome",
    "1.7": "Motorsports",
    "1.7.1": "Formula 1",
    "1.7.2": "NASCAR",
    "1.8": "College Sports",
    "1.8.1": "NCAAB (Basketball)",
    "1.9": "Other Sports",
    "1.9.1": "Chess",
    "1.9.2": "Cricket (IPL)",
    "1.9.3": "Golf",
    "2": "Politics",
    "2.1": "US Politics",
    "2.1.1": "Elections",
    "2.1.2": "Government Officials",
    "2.1.3": "Political Actions",
    "2.1.4": "Speeches & Debates",
    "2.2": "International Politics",
    "2.2.1": "National Elections",
    "3": "Finance",
    "3.1": "Macroeconomics",
    "3.1.1": "Inflation",
    "3.1.2": "Interest Rates",
    "3.1.3": "GDP",
    "3.2": "Cryptocurrency",
    "3.2.1": "Price Prediction",
    "3.2.2": "Tokenomics & Performance",
    "3.2.3": "Industry & Company Events",
    "3.2.4": "Protocol Development",
    "3.3": "Traditional Markets",
    "3.3.1": "Company Performance",
    "3.3.2": "Commodities",
    "4": "Entertainment & Culture",
    "4.1": "Movies",
    "4.1.1": "Box Office",
    "4.2": "Awards & Ceremonies",
    "4.2.1": "Film Awards",
    "4.3": "Celebrities & Public Figures",
    "4.3.1": "Public Actions",
    "4.4": "Music",
    "4.4.1": "Album Performance",
    "4.4.2": "Competitions",
    "4.5": "Television",
    "4.5.1": "Plot Outcomes",
    "5": "Geopolitics & World Events",
    "5.1": "International Relations",
    "5.1.1": "Alliances",
    "5.2": "Conflict & Security",
    "5.2.1": "Military Actions",
    "5.3": "Public Health",
    "5.3.1": "Global Health Crises",
    "5.4": "Environment & Disasters",
    "5.4.1": "Weather",
    "5.4.2": "Climate",
    "6": "Technology",
    "6.1": "Artificial Intelligence",
    "6.1.1": "Product Development",
    "6.2": "Social Media",
    "6.2.1": "Platform Stability",
    "6.3": "Space Exploration",
    "6.3.1": "Launches",
    "7": "Miscellaneous",
    "7.1": "Legal & Court Cases",
    "7.2": "Science & Discovery",
    "7.3": "General Events",
}

# ---- Removed: local KV cache implementation ----


@dataclass
class MarketRow:
    row_id: int
    market_id: str
    question: str
    description: str | None
    tags: List[str]
    fetched_at: str | None
    market_category: str | None


class GeminiCategorizer:
    def __init__(self, api_key: str, temperature: float = 0.0, cached_content_name: Optional[str] = None):
        self.client = genai.Client(api_key=api_key)
        self.temperature = temperature
        self.cached_content_name = cached_content_name  # name/id of server-side cache, if any

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        Note: 'system_prompt' is *only* used when explicit caching is disabled or unavailable.
        When caching is enabled, the system instruction must be part of the cached content.
        """
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            # If we created a cache, attach its name so the model reuses cached tokens.
            cached_content=self.cached_content_name if self.cached_content_name else None,
            # If no cache, pass system instruction on each call.
            system_instruction=None if self.cached_content_name else system_prompt,
        )

        response = self.client.models.generate_content(
            model=MODEL_NAME,
            contents=user_prompt,
            config=config,
        )
        payload = (getattr(response, "text", "") or "").strip()
        if not payload:
            payload = join_candidate_text(response)
        if not payload:
            raise ValueError("Model returned empty response")
        return payload


def join_candidate_text(response: Any) -> str:
    fragments: List[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                fragments.append(text)
    return "\n".join(fragment.strip() for fragment in fragments if fragment).strip()


def load_api_key() -> str:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_API_KEY (preferred) or GEMINI_API_KEY before running categorization.")
    return api_key.strip()


def ensure_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN \"{column}\" TEXT")
    conn.commit()


def category_level_column_names(base_column: str) -> Tuple[str, str, str]:
    return (f"{base_column}_l1", f"{base_column}_l2", f"{base_column}_l3")


def ensure_category_level_columns(conn: sqlite3.Connection, table: str, base_column: str) -> Tuple[str, str, str]:
    level_columns = category_level_column_names(base_column)
    for column in level_columns:
        ensure_column(conn, table, column)
    return level_columns


def category_name_column_names(base_column: str) -> Tuple[str, str, str, str]:
    return (
        f"{base_column}_name",
        f"{base_column}_l1_name",
        f"{base_column}_l2_name",
        f"{base_column}_l3_name",
    )


def ensure_category_name_columns(conn: sqlite3.Connection, table: str, base_column: str) -> Tuple[str, str, str, str]:
    name_columns = category_name_column_names(base_column)
    for column in name_columns:
        ensure_column(conn, table, column)
    return name_columns


def split_category_levels(code: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not code:
        return (None, None, None)
    parts = [part.strip() for part in code.split(".") if part.strip()]
    levels: List[Optional[str]] = []
    for idx in range(3):
        levels.append(parts[idx] if idx < len(parts) else None)
    return levels[0], levels[1], levels[2]


def build_level_codes(code: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not code:
        return (None, None, None)
    parts = [part.strip() for part in code.split(".") if part.strip()]
    codes: List[Optional[str]] = []
    for idx in range(1, 4):
        if idx <= len(parts):
            codes.append(".".join(parts[:idx]))
        else:
            codes.append(None)
    return codes[0], codes[1], codes[2]


def fetch_rows(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    limit: Optional[int],
    force: bool,
) -> List[MarketRow]:
    conn.row_factory = sqlite3.Row
    base_query = f"SELECT row_id, market_id, question, description, tags, fetched_at, \"{column}\" as market_category FROM {table}"
    params: Sequence[Any] = []
    if force:
        query = f"{base_query} ORDER BY row_id"
    else:
        query = (
            f"{base_query} WHERE (\"{column}\" IS NULL OR TRIM(\"{column}\") = '') "
            "ORDER BY row_id"
        )
    if limit is not None:
        query += " LIMIT ?"
        params = list(params) + [limit]
    rows = conn.execute(query, params).fetchall()
    market_rows: List[MarketRow] = []
    for row in rows:
        tags_raw = row["tags"]
        tags: List[str] = []
        if tags_raw:
            try:
                parsed = json.loads(tags_raw)
                if isinstance(parsed, list):
                    tags = [str(item) for item in parsed if item]
                else:
                    tags = [str(parsed)]
            except json.JSONDecodeError:
                tags = [str(tags_raw)]
        market_rows.append(
            MarketRow(
                row_id=int(row["row_id"]),
                market_id=str(row["market_id"]),
                question=str(row["question"] or ""),
                description=row["description"],
                tags=tags,
                fetched_at=row["fetched_at"],
                market_category=row["market_category"],
            )
        )
    return market_rows


def chunked(items: Sequence[MarketRow], size: int) -> Iterable[List[MarketRow]]:
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def build_system_prompt(category_text: str) -> str:
    return (
        "You are a rigorous classifier for prediction markets. "
        "Always return the most specific valid category code from the taxonomy.\n\n"
        "Category taxonomy:\n"
        f"{category_text.strip()}"
    )


def truncate(text: Optional[str], max_chars: int = 800) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def build_user_prompt(rows: Sequence[MarketRow]) -> str:
    payload = []
    for row in rows:
        payload.append(
            {
                "row_id": row.row_id,
                "market_id": row.market_id,
                "question": truncate(row.question, 600),
                "description": truncate(row.description, 600),
                "tags": row.tags,
            }
        )
    guidance = (
        "Classify each market using the taxonomy. Guidance:\n"
        "- Choose the most specific leaf code (e.g. 1.4.1).\n"
        "- If nothing matches, respond with '7.3'.\n"
        "- Return one line per market in the format '<row_id>\t<category_code>'.\n"
        "- Never include commentary, markdown, or extra text."
    )
    return f"{guidance}\n\nMarkets JSON:\n{json.dumps(payload, ensure_ascii=False)}"


def parse_model_output(raw: str) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "\t" in stripped:
            parts = stripped.split("\t", 1)
        elif ":" in stripped:
            parts = stripped.split(":", 1)
        else:
            parts = stripped.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"Cannot parse line: '{stripped}'")
        row_token, code_token = parts[0].strip(), parts[1].strip()
        if not row_token.isdigit():
            raise ValueError(f"Row id is not an integer in line: '{stripped}'")
        mapping[int(row_token)] = code_token
    return mapping


def update_rows(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    level_columns: Tuple[str, str, str],
    name_columns: Tuple[str, str, str, str],
    taxonomy_names: Dict[str, str],
    assignments: Dict[int, str],
) -> None:
    col_l1, col_l2, col_l3 = level_columns
    col_name, col_name_l1, col_name_l2, col_name_l3 = name_columns
    for row_id, category in assignments.items():
        level_values = split_category_levels(category)
        level_codes = build_level_codes(category)
        category_name = taxonomy_names.get(category or "")
        level_name_values = (
            taxonomy_names.get(level_codes[0] or "") if level_codes[0] else None,
            taxonomy_names.get(level_codes[1] or "") if level_codes[1] else None,
            taxonomy_names.get(level_codes[2] or "") if level_codes[2] else None,
        )
        conn.execute(
            (
                f"UPDATE {table} SET \"{column}\" = ?, \"{col_l1}\" = ?, \"{col_l2}\" = ?, \"{col_l3}\" = ?, "
                f"\"{col_name}\" = ?, \"{col_name_l1}\" = ?, \"{col_name_l2}\" = ?, \"{col_name_l3}\" = ? "
                "WHERE row_id = ?"
            ),
            (
                category,
                *level_values,
                category_name,
                level_name_values[0],
                level_name_values[1],
                level_name_values[2],
                row_id,
            ),
        )
    conn.commit()


def write_jsonl(log_path: Path, records: Iterable[Dict[str, Any]]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def create_explicit_cache(
    client: genai.Client,
    taxonomy_text: str,
    display_name: str,
    ttl_seconds: int,
) -> Optional[str]:
    """
    Creates a server-side cache that includes the system instruction and the taxonomy file.
    Returns the cache 'name' to pass via GenerateContentConfig(cached_content=...),
    or None if creation fails (e.g., unsupported model).
    """
    try:
        # Upload taxonomy via Files API for robust long-context handling
        taxonomy_bytes = taxonomy_text.encode("utf-8")
        file_obj = io.BytesIO(taxonomy_bytes)
        uploaded = client.files.upload(
            file=file_obj,
            config=dict(mime_type="text/markdown", display_name="polymarket_taxonomy.md"),
        )

        cache = client.caches.create(
            model=MODEL_NAME,
            config=types.CreateCachedContentConfig(
                display_name=display_name,
                system_instruction=(
                    "You are a rigorous classifier for prediction markets. "
                    "Always return the most specific valid category code from the taxonomy."
                ),
                contents=[uploaded],
                ttl=f"{int(ttl_seconds)}s" if ttl_seconds > 0 else None,
            ),
        )
        return cache.name
    except Exception as e:
        # Fallback silently; caller may log if desired
        print(f"[warn] Explicit caching unavailable or failed: {e}")
        return None


def categorize_batches(
    rows: Sequence[MarketRow],
    client: GeminiCategorizer,
    system_prompt: str,
    batch_size: int,
    table: str,
    column: str,
    level_columns: Tuple[str, str, str],
    name_columns: Tuple[str, str, str, str],
    taxonomy_names: Dict[str, str],
    conn: sqlite3.Connection,
    log_path: Optional[Path],
) -> None:
    if not rows:
        return

    for batch in chunked(rows, batch_size):
        user_prompt = build_user_prompt(batch)
        raw_output = client.generate(system_prompt, user_prompt)
        parsed = parse_model_output(raw_output)
        if set(parsed.keys()) != {row.row_id for row in batch}:
            missing = {row.row_id for row in batch} - set(parsed.keys())
            extra = set(parsed.keys()) - {row.row_id for row in batch}
            raise ValueError(
                f"Model response mismatch. Missing: {missing or 'none'}, Extra: {extra or 'none'}"
            )

        update_rows(conn, table, column, level_columns, name_columns, taxonomy_names, parsed)

        if log_path:
            now = datetime.now(timezone.utc).isoformat()
            records = []
            for row in batch:
                level_values = split_category_levels(parsed[row.row_id])
                level_codes = build_level_codes(parsed[row.row_id])
                record_category_name = taxonomy_names.get(parsed[row.row_id], None)
                level_name_values = (
                    taxonomy_names.get(level_codes[0]) if level_codes[0] else None,
                    taxonomy_names.get(level_codes[1]) if level_codes[1] else None,
                    taxonomy_names.get(level_codes[2]) if level_codes[2] else None,
                )
                records.append(
                    {
                        "row_id": row.row_id,
                        "market_id": row.market_id,
                        "category": parsed[row.row_id],
                        "category_l1": level_values[0],
                        "category_l2": level_values[1],
                        "category_l3": level_values[2],
                        "category_name": record_category_name,
                        "category_l1_name": level_name_values[0],
                        "category_l2_name": level_name_values[1],
                        "category_l3_name": level_name_values[2],
                        "source": "model",
                        "prompt": user_prompt,
                        "output": raw_output,
                        "timestamp": now,
                        "cached_content": bool(client.cached_content_name),
                    }
                )
            write_jsonl(log_path, records)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Categorize Polymarket markets in batches using Gemini with server-side caching")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Path to polymarket_markets.db")
    parser.add_argument("--table", default="polymarket_markets", help="Table name (default: polymarket_markets)")
    parser.add_argument(
        "--column",
        default="market_category",
        help="Column to populate with the category code (default: market_category)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of markets per Gemini request (default: 32)",
    )
    parser.add_argument(
        "--jsonl-out",
        type=Path,
        default=DEFAULT_JSONL_LOG,
        help="Audit log JSONL path (use '-' to disable logging)",
    )
    parser.add_argument("--limit", type=int, help="Process at most this many rows")
    parser.add_argument("--temperature", type=float, default=0.0, help="Gemini temperature (default: 0.0)")
    parser.add_argument("--force", action="store_true", help="Re-label even if the column already has a value")
    parser.add_argument(
        "--cache-ttl-seconds",
        type=int,
        default=3600,
        help="TTL for explicit server-side cache (default: 3600). Set 0 to use default TTL.",
    )
    parser.add_argument(
        "--no-explicit-cache",
        action="store_true",
        help="Disable explicit caching (only implicit caching may apply on 2.5 models).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be positive when provided")

    api_key = load_api_key()
    category_reference = CATEGORY_REFERENCE_PATH.read_text(encoding="utf-8")
    taxonomy_names = CATEGORY_NAME_MAP
    system_prompt = build_system_prompt(category_reference)
    log_path = None if str(args.jsonl_out) == "-" else args.jsonl_out

    # Build explicit cache (system instruction + taxonomy) unless disabled.
    cached_content_name: Optional[str] = None
    client_raw = genai.Client(api_key=api_key)

    if not args.no_explicit_cache:
        cached_content_name = create_explicit_cache(
            client=client_raw,
            taxonomy_text=category_reference,
            display_name="polymarket-taxonomy-cache",
            ttl_seconds=args.cache_ttl_seconds,
        )
        if cached_content_name:
            print(f"[info] Using explicit cached_content: {cached_content_name}")
        else:
            print("[info] Proceeding without explicit cache (will include system prompt per call).")

    client = GeminiCategorizer(
        api_key=api_key,
        temperature=args.temperature,
        cached_content_name=cached_content_name,
    )

    with sqlite3.connect(args.db) as conn:
        ensure_column(conn, args.table, args.column)
        level_columns = ensure_category_level_columns(conn, args.table, args.column)
        name_columns = ensure_category_name_columns(conn, args.table, args.column)
        rows = fetch_rows(conn, args.table, args.column, args.limit, args.force)
        if not rows:
            print("No markets require categorization.")
            return
        categorize_batches(
            rows=rows,
            client=client,
            system_prompt=system_prompt,
            batch_size=args.batch_size,
            table=args.table,
            column=args.column,
            level_columns=level_columns,
            name_columns=name_columns,
            taxonomy_names=taxonomy_names,
            conn=conn,
            log_path=log_path,
        )

    print(f"Categorized {len(rows)} market rows; results stored in column '{args.column}'.")


if __name__ == "__main__":
    main()
