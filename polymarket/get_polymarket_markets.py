#!/usr/bin/env python3
"""CLI utility to snapshot Polymarket's active markets into JSONL and SQLite.

Usage examples::

    # Fetch the default set of markets and populate polymarket_markets.db
    python get_polymarket_markets.py

    # Fetch simplified markets, limit to 250 rows, and write to custom locations
    python get_polymarket_markets.py \
        --limit 10000 \
        --db data/polymarket_markets.db \
        custom_markets.jsonl

    # Disable the row limit (grab every active market)
    python get_polymarket_markets.py --limit 0

The script streams current markets via the Polymarket CLOB API, writes one
record per line to JSONL, produces a lightweight summary JSONL, and keeps a
normalized mirror table (`polymarket_markets`) in SQLite for downstream use.
"""

import argparse
import json
import sqlite3
from datetime import datetime, UTC
import hashlib
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests

BASE = "https://clob.polymarket.com"

def _is_tradable_market(market: Dict[str, Any]) -> bool:
    """Return True when the market is trading and not closed/archived."""
    if not market.get("active", False):
        return False
    if market.get("closed"):
        return False
    if market.get("archived"):
        return False
    accepting_orders = market.get("accepting_orders")
    # Polymarket occasionally omits this flag, so only exclude when explicitly false.
    if accepting_orders is False:
        return False
    return True


def iter_markets(
    simplified: bool = False,
    timeout: int = 15,
    limit: Optional[int] = None,
) -> Iterable[Dict]:
    """Yield currently tradable markets from Polymarket CLOB, paging by next_cursor."""
    path = "/simplified-markets" if simplified else "/markets"
    cursor: Optional[str] = None
    yielded = 0
    with requests.Session() as s:
        while True:
            params = {"active": "true"}
            if cursor:
                params["next_cursor"] = cursor
            resp = s.get(f"{BASE}{path}", params=params, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get("data") or payload.get("markets") or []
            for m in items:
                if _is_tradable_market(m):
                    yield m
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
            cursor = payload.get("next_cursor")
            if not cursor:
                break

def _quote_identifier(name: str) -> str:
    """Return a SQLite-safe quoted identifier."""
    return f'"{name.replace("\"", "\"\"")}"'


def _infer_sql_type(value: Any) -> str:
    """Infer a reasonable SQLite column type from a Python value."""
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    return "TEXT"


def _normalize_market_record(market: Dict) -> Dict[str, Any]:
    """Normalize market values for SQLite insertion."""
    normalized: Dict[str, Any] = {}
    for key, value in market.items():
        if isinstance(value, (dict, list)):
            normalized[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            normalized[key] = int(value)
        else:
            normalized[key] = value
    return normalized


def _resolve_market_id(market: Dict, simplified: bool, serialized: str) -> str:
    """Return a stable identifier for a market, falling back to a hash."""
    candidates = [
        market.get("id"),
        market.get("market_slug"),
        market.get("question_id"),
        market.get("condition_id"),
    ]

    if simplified:
        for token in market.get("tokens") or []:
            token_id = token.get("token_id")
            if token_id:
                candidates.append(token_id)

    for candidate in candidates:
        if candidate:
            return str(candidate)

    warnings.warn(
        "Falling back to content hash for market identifier", RuntimeWarning
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def _ensure_columns(
    conn: sqlite3.Connection,
    existing_columns: set[str],
    values: Dict[str, Any],
) -> set[str]:
    """Add missing columns based on the provided values and update the cache."""
    for column, value in values.items():
        if column in {"market_id", "fetched_at"} or column in existing_columns:
            continue
        sql_type = _infer_sql_type(value)
        conn.execute(
            f"ALTER TABLE polymarket_markets ADD COLUMN {_quote_identifier(column)} {sql_type}"
        )
        existing_columns.add(column)
    return existing_columns


def dump_markets(
    output_path: Path,
    db_path: Path,
    simplified: bool,
    timeout: int,
    limit: Optional[int] = None,
) -> int:
    """Write markets to JSONL, summary JSONL, and SQLite; return written count."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    timestamp = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    summary_path = output_path.with_name("markets.jsonl")

    with sqlite3.connect(db_path) as conn, output_path.open("w", encoding="utf-8") as fh, summary_path.open(
        "w", encoding="utf-8"
    ) as sh:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS polymarket_markets (
                market_id TEXT PRIMARY KEY,
                fetched_at TEXT NOT NULL,
                market_json TEXT NOT NULL
            )
            """
        )

        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(polymarket_markets)")
        }

        for market in iter_markets(simplified=simplified, timeout=timeout, limit=limit):
            row_id = count + 1
            serialized = json.dumps(market, ensure_ascii=False)
            market_id = _resolve_market_id(market, simplified=simplified, serialized=serialized)
            fh.write(serialized)
            fh.write("\n")

            summary_payload = {
                "row_id": row_id,
                "name": market.get("question")
                or market.get("market_slug")
                or str(market_id),
                "description": market.get("description"),
            }
            sh.write(json.dumps(summary_payload, ensure_ascii=False))
            sh.write("\n")

            normalized = _normalize_market_record(market)
            normalized["row_id"] = row_id
            normalized["market_json"] = serialized

            existing_columns = _ensure_columns(conn, existing_columns, normalized)

            insert_columns = ["market_id", "fetched_at", *normalized.keys()]
            insert_identifiers = ", ".join(_quote_identifier(col) for col in insert_columns)
            placeholders = ", ".join("?" for _ in insert_columns)
            update_columns = [col for col in insert_columns if col != "market_id"]
            update_clause = ", ".join(
                f"{_quote_identifier(col)}=excluded.{_quote_identifier(col)}"
                for col in update_columns
            )

            values = [
                str(market_id),
                timestamp,
                *[normalized[col] for col in normalized.keys()],
            ]

            conn.execute(
                f"""
                INSERT INTO polymarket_markets ({insert_identifiers})
                VALUES ({placeholders})
                ON CONFLICT(market_id) DO UPDATE SET
                    {update_clause}
                """,
                values,
            )

            count += 1

        conn.commit()

    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dump Polymarket markets to JSONL and SQLite"
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=Path("polymarket_markets.jsonl"),
        help="Destination JSONL file (default: polymarket_markets.jsonl).",
    )
    parser.add_argument(
        "--simplified",
        action="store_true",
        help="Use the simplified markets endpoint.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Per-request timeout in seconds (default: 15).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3000,
        help="Maximum active markets to fetch (default: 3000; use 0 for no limit).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("/Users/jaidevshah/agentic_search/data/polymarket_markets.db"),
        help=(
            "Destination SQLite database file "
            "(default: /Users/jaidevshah/agentic_search/data/polymarket_markets.db)."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    limit = None if args.limit is None or args.limit <= 0 else args.limit
    written = dump_markets(args.output, args.db, args.simplified, args.timeout, limit)
    print(
        f"Wrote {written} market entries to {args.output} and {args.db}"
    )