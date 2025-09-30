#!/usr/bin/env python3
"""Join Polymarket base and gamma SQLite databases into a single enriched snapshot.

The script expects:
- A base database with the table `polymarket_markets` (default: polymarket/data/polymarket_markets.db)
- A gamma database with the table `polymarket_markets_gamma` (default: data/polymarket_gamma.db)

It writes the joined results to `polymarket/data/polymarket_markets_data_enriched.db` by default,
creating a table named `polymarket_markets_enriched`.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_BASE_DB = Path("polymarket/data/polymarket_markets.db")
DEFAULT_GAMMA_DB = Path("/Users/jaidevshah/agentic_search/polymarket/data/polymarket_gamma.db")
DEFAULT_OUTPUT_DB = Path("polymarket/data/polymarket_markets_data_enriched.db")


def quote_path(path: Path) -> str:
    """Return a single-quoted path safe for ATTACH statements."""
    return f"'{str(path).replace("'", "''")}'"


def build_enriched_database(base_db: Path, gamma_db: Path, output_db: Path) -> None:
    for path, label in ((base_db, "base"), (gamma_db, "gamma")):
        if not path.exists():
            raise FileNotFoundError(f"{label} database not found: {path}")

    output_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output_db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        attached_base = False
        attached_gamma = False
        try:
            conn.execute(f"ATTACH DATABASE {quote_path(base_db)} AS base")
            attached_base = True
            conn.execute(f"ATTACH DATABASE {quote_path(gamma_db)} AS gamma")
            attached_gamma = True
            conn.execute("DROP TABLE IF EXISTS polymarket_markets_enriched")
            conn.execute(
                """
                CREATE TABLE polymarket_markets_enriched AS
                SELECT
                    b.*,
                    g.fetched_at AS gamma_fetched_at,
                    g.slug AS gamma_slug,
                    g.question AS gamma_question,
                    g.outcome_prices,
                    g.last_trade_price,
                    g.best_bid,
                    g.best_ask,
                    g.liquidity_num,
                    g.liquidity_amm,
                    g.liquidity_clob,
                    g.volume_num
                FROM base.polymarket_markets AS b
                INNER JOIN gamma.polymarket_markets_gamma AS g
                    ON b.market_id = g.market_id
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_polymarket_markets_enriched_market_id ON polymarket_markets_enriched(market_id)"
            )
        finally:
            if attached_gamma:
                conn.execute("DETACH DATABASE gamma")
            if attached_base:
                conn.execute("DETACH DATABASE base")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Join Polymarket SQLite databases into an enriched snapshot")
    parser.add_argument(
        "--base-db",
        type=Path,
        default=DEFAULT_BASE_DB,
        help=f"Path to the base Polymarket markets DB (default: {DEFAULT_BASE_DB}).",
    )
    parser.add_argument(
        "--gamma-db",
        type=Path,
        default=DEFAULT_GAMMA_DB,
        help=f"Path to the gamma markets DB (default: {DEFAULT_GAMMA_DB}).",
    )
    parser.add_argument(
        "--output-db",
        type=Path,
        default=DEFAULT_OUTPUT_DB,
        help=f"Destination for the enriched DB (default: {DEFAULT_OUTPUT_DB}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        build_enriched_database(args.base_db, args.gamma_db, args.output_db)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Enriched database written to {args.output_db}")


if __name__ == "__main__":
    main()
