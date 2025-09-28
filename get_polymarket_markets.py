#!/usr/bin/env python3
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

import requests

BASE = "https://clob.polymarket.com"

def iter_markets(
    simplified: bool = False,
    timeout: int = 15,
    limit: Optional[int] = None,
) -> Iterable[Dict]:
    """Yield active markets from Polymarket CLOB, transparently paging by next_cursor."""
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
                if m.get("active"):
                    yield m
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
            cursor = payload.get("next_cursor")
            if not cursor:
                break

def dump_markets(
    output_path: Path,
    db_path: Path,
    simplified: bool,
    timeout: int,
    limit: Optional[int] = None,
) -> int:
    """Write markets to JSONL and SQLite; return the number of written records."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    timestamp = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    with sqlite3.connect(db_path) as conn, output_path.open("w", encoding="utf-8") as fh:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS polymarket_markets (
                market_id TEXT PRIMARY KEY,
                market_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )

        for market in iter_markets(simplified=simplified, timeout=timeout, limit=limit):
            market_id = market.get("id")
            if market_id is None:
                raise KeyError("Encountered market without an 'id' field; cannot persist")

            serialized = json.dumps(market, ensure_ascii=False)
            fh.write(serialized)
            fh.write("\n")

            conn.execute(
                """
                INSERT INTO polymarket_markets (market_id, market_json, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(market_id) DO UPDATE SET
                    market_json=excluded.market_json,
                    fetched_at=excluded.fetched_at
                """,
                (str(market_id), serialized, timestamp),
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
