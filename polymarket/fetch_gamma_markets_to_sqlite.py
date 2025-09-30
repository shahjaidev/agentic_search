#!/usr/bin/env python3
"""Fetch Polymarket markets from the gamma API and load them into SQLite.

The script mirrors a subset of the per-market pricing and liquidity fields so
that downstream analytics can run locally without polling the API. By default
it writes to `data/polymarket_gamma.db` and upserts into a table named
`polymarket_markets_gamma`.

Usage::

    python polymarket/fetch_gamma_markets_to_sqlite.py \
        --db /Users/jaidevshah/agentic_search/polymarket/data/polymarket_gamma.db \
        --throttle 0.02 \

The command requires outbound network access to `gamma-api.polymarket.com`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

BASE = "https://gamma-api.polymarket.com"
LIMIT = 250  # Current maximum supported by the public API
END_TIME_KEYS = (
    "endDate",
    "endDateISO",
    "endDateIso",
    "end_date",
    "end_date_iso",
    "closesAt",
    "closeDate",
    "closeTime",
    "resolveTime",
    "resolutionTime",
    "expiry",
    "expiryTime",
)
MARKET_ID_KEYS = (
    "slug",
    "marketSlug",
    "market_slug",
    "id",
    "questionId",
    "question_id",
    "conditionId",
    "condition_id",
)
logger = logging.getLogger(__name__)


def fetch_all_markets(
    limit: int = LIMIT,
    throttle: float = 0.15,
    timeout: int = 15,
    max_markets: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return every active market exposed by the gamma API."""
    markets: List[Dict[str, Any]] = []
    offset = 0
    session = requests.Session()
    now = datetime.now(timezone.utc)
    try:
        while True:
            resp = session.get(
                f"{BASE}/markets",
                params={
                    "limit": limit,
                    "offset": offset,
                    "closed": "false",
                    "order": "endDate",
                    "ascending": "true",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for market in batch:
                if not _market_ends_in_future(market, now):
                    logger.debug(
                        "Skipping market %s because end time is not in the future",
                        market.get("id") or market.get("slug") or "<unknown>",
                    )
                    continue
                markets.append(market)
            offset += limit
            if max_markets is not None and max_markets > 0 and len(markets) >= max_markets:
                markets = markets[:max_markets]
                logger.info("Reached max markets limit (%d)", max_markets)
                break
            logger.info("Fetched %d markets so far", len(markets))
            if throttle:
                time.sleep(throttle)
    finally:
        session.close()
    logger.info("Total markets fetched: %d", len(markets))
    return markets


def normalise_market(market: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten and serialise complex fields so sqlite3 can persist them."""
    outcome_prices = market.get("outcomePrices")
    market_id = _resolve_market_id(market)
    return {
        "market_id": market_id,
        "slug": market.get("slug"),
        "question": market.get("question"),
        "outcome_prices": json.dumps(outcome_prices) if outcome_prices is not None else None,
        "last_trade_price": _safe_float(market.get("lastTradePrice")),
        "best_bid": _safe_float(market.get("bestBid")),
        "best_ask": _safe_float(market.get("bestAsk")),
        "liquidity_num": _safe_float(market.get("liquidityNum")),
        "liquidity_amm": _safe_float(market.get("liquidityAmm")),
        "liquidity_clob": _safe_float(market.get("liquidityClob")),
        "volume_num": _safe_float(market.get("volumeNum")),
    }


def _safe_float(value: Any) -> Optional[float]:
    """Return a float when possible, otherwise None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_market_id(market: Dict[str, Any]) -> str:
    """Choose a stable identifier aligned with the base Polymarket snapshot."""
    for key in MARKET_ID_KEYS:
        value = market.get(key)
        if value:
            return str(value)
    raise ValueError("Market payload missing an identifier")


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse ISO8601 strings or epoch timestamps into aware datetimes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
    return None


def _market_ends_in_future(market: Dict[str, Any], now: datetime) -> bool:
    """Return True when the market has an end time after `now`.

    Markets without a parseable end timestamp are retained to avoid
    unintentionally dropping valid rows when metadata is missing.
    """
    for key in END_TIME_KEYS:
        if key in market:
            end_dt = _parse_datetime(market.get(key))
            if end_dt is not None:
                return end_dt > now
    # Some APIs nest timing metadata under `event` or `market` keys.
    nested = market.get("event") or market.get("market")
    if isinstance(nested, dict):
        for key in END_TIME_KEYS:
            if key in nested:
                end_dt = _parse_datetime(nested.get(key))
                if end_dt is not None:
                    return end_dt > now
    return True


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the polymarket table if it is missing."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS polymarket_markets_gamma (
            market_id TEXT PRIMARY KEY,
            fetched_at TEXT NOT NULL,
            slug TEXT,
            question TEXT,
            outcome_prices TEXT,
            last_trade_price REAL,
            best_bid REAL,
            best_ask REAL,
            liquidity_num REAL,
            liquidity_amm REAL,
            liquidity_clob REAL,
            volume_num REAL
        )
        """
    )


def upsert_markets(conn: sqlite3.Connection, markets: Iterable[Dict[str, Any]]) -> int:
    """Insert or replace market rows, returning the number written."""
    ensure_schema(conn)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows_inserted = 0
    sql = """
        INSERT INTO polymarket_markets_gamma (
            market_id,
            fetched_at,
            slug,
            question,
            outcome_prices,
            last_trade_price,
            best_bid,
            best_ask,
            liquidity_num,
            liquidity_amm,
            liquidity_clob,
            volume_num
        )
        VALUES (
            :market_id,
            :fetched_at,
            :slug,
            :question,
            :outcome_prices,
            :last_trade_price,
            :best_bid,
            :best_ask,
            :liquidity_num,
            :liquidity_amm,
            :liquidity_clob,
            :volume_num
        )
        ON CONFLICT(market_id) DO UPDATE SET
            fetched_at=excluded.fetched_at,
            slug=excluded.slug,
            question=excluded.question,
            outcome_prices=excluded.outcome_prices,
            last_trade_price=excluded.last_trade_price,
            best_bid=excluded.best_bid,
            best_ask=excluded.best_ask,
            liquidity_num=excluded.liquidity_num,
            liquidity_amm=excluded.liquidity_amm,
            liquidity_clob=excluded.liquidity_clob,
            volume_num=excluded.volume_num
    """
    with conn:
        for market in markets:
            try:
                payload = normalise_market(market)
            except ValueError:
                logger.warning(
                    "Skipping market without stable identifier: %s",
                    market.get("slug") or market.get("id") or "<unknown>",
                )
                continue
            payload["fetched_at"] = fetched_at
            conn.execute(sql, payload)
            rows_inserted += 1
    return rows_inserted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Snapshot Polymarket gamma API data into SQLite")
    default_db = Path("/Users/jaidevshah/agentic_search/polymarket/data/polymarket_gamma.db")
    parser.add_argument(
        "--db",
        type=Path,
        default=default_db,
        help=f"Destination SQLite database (default: {default_db}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=LIMIT,
        help="Page size for API requests (default: 250).",
    )
    parser.add_argument(
        "--throttle",
        type=float,
        default=0.15,
        help="Sleep duration between API requests in seconds (default: 0.15).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Per-request timeout in seconds (default: 15).",
    )
    parser.add_argument(
        "--max-markets",
        type=int,
        default=0,
        help="Maximum number of markets to collect (default: 0 for all).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path: Path = args.db
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    max_markets = args.max_markets if args.max_markets > 0 else None
    markets = fetch_all_markets(
        limit=args.limit,
        throttle=args.throttle,
        timeout=args.timeout,
        max_markets=max_markets,
    )

    with sqlite3.connect(db_path) as conn:
        written = upsert_markets(conn, markets)
    logger.info("Persisted %d markets into %s", written, db_path)
    print(f"Persisted {written} markets to {db_path}")


if __name__ == "__main__":
    main()
