#!/usr/bin/env python3
"""
Fetch YC OSS API company data and sync it into a local SQLite database.

Args (CLI flags):
  --out PATH          Path for the debug JSONL dump (default: yc_db.jsonl).
  --skip-jsonl        Skip writing the debug JSONL altogether.
  --from-jsonl PATH   Load data from an existing JSONL file instead of fetching.
  --also LIST [...]   Optional extra subsets to download (e.g. top, hiring).
  --save-meta         Persist meta.json alongside the JSONL for provenance.
  --sqlite-url URL    Override the SQLite database URL (default: sqlite:///data/yc_db.db).
  --limit N           Only process the first N companies (useful for sampling).

Example:
  python yc_loader.py --also top hiring --save-meta --limit 1000 --sqlite-url sqlite:///data/yc_custom.db

By default the script downloads the latest "all" companies list, stores a
debugging JSONL snapshot, and mirrors the records into SQLite. You can reuse
an existing JSONL dump instead of hitting the network with ``--from-jsonl``.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE = "https://yc-oss.github.io/api"
COMPANY_SOURCES = {
    "all": f"{BASE}/companies/all.json",         # all launched companies
    "top": f"{BASE}/companies/top.json",         # YC “top companies” subset
    "hiring": f"{BASE}/companies/hiring.json",   # currently hiring subset
    "black-founded": f"{BASE}/companies/black-founded.json",
    "hispanic-latino-founded": f"{BASE}/companies/hispanic-latino-founded.json",
    "women-founded": f"{BASE}/companies/women-founded.json",
    "nonprofit": f"{BASE}/companies/nonprofit.json",
}
META_URL = f"{BASE}/meta.json"

DEFAULT_JSONL = "yc_db.jsonl"
DEFAULT_SQLITE_URL = "sqlite:///data/yc_db.db"

JSON_FIELDS = {
    "former_names",
    "tags",
    "tags_highlighted",
    "industries",
    "regions",
    "app_answers",
}

BOOLEAN_FIELDS = {
    "top_company",
    "isHiring",
    "nonprofit",
    "app_video_public",
    "demo_day_video_public",
    "question_answers",
}

INTEGER_FIELDS = {
    "id",
    "team_size",
    "launched_at",
}

COLUMN_ORDER = [
    "id",
    "name",
    "slug",
    "former_names",
    "small_logo_thumb_url",
    "website",
    "all_locations",
    "long_description",
    "one_liner",
    "team_size",
    "industry",
    "subindustry",
    "launched_at",
    "tags",
    "tags_highlighted",
    "top_company",
    "isHiring",
    "nonprofit",
    "batch",
    "status",
    "industries",
    "regions",
    "stage",
    "app_video_public",
    "demo_day_video_public",
    "app_answers",
    "question_answers",
    "url",
    "api",
]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS yc_companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT,
    former_names TEXT,
    small_logo_thumb_url TEXT,
    website TEXT,
    all_locations TEXT,
    long_description TEXT,
    one_liner TEXT,
    team_size INTEGER,
    industry TEXT,
    subindustry TEXT,
    launched_at INTEGER,
    tags TEXT,
    tags_highlighted TEXT,
    top_company INTEGER,
    isHiring INTEGER,
    nonprofit INTEGER,
    batch TEXT,
    status TEXT,
    industries TEXT,
    regions TEXT,
    stage TEXT,
    app_video_public INTEGER,
    demo_day_video_public INTEGER,
    app_answers TEXT,
    question_answers INTEGER,
    url TEXT,
    api TEXT
)
""".strip()


def fetch_json(url: str, retries: int = 3, backoff: float = 1.5) -> Any:
    """GET a JSON payload with simple retries using stdlib only."""

    attempt = 0
    while True:
        try:
            req = Request(url, headers={"User-Agent": "yc-loader/1.0"})
            with urlopen(req, timeout=60) as resp:
                if resp.status != 200:
                    raise HTTPError(url, resp.status, "Bad status", hdrs=resp.headers, fp=None)
                data = resp.read()
                return json.loads(data.decode("utf-8"))
        except (URLError, HTTPError) as exc:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(backoff ** attempt)


def write_jsonl(records: Iterable[Dict[str, Any]], path: Path) -> None:
    """Write an iterable of dicts to a JSONL file (UTF-8, no ASCII escaping)."""

    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file into memory."""

    data: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data.append(json.loads(line))
    return data


def resolve_database_path(database_url: str | None = None) -> Path:
    """Resolve the SQLite path from DATABASE_URL or a provided override."""

    db_url = database_url or os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)
    parsed = urlparse(db_url)
    if parsed.scheme != "sqlite":
        raise ValueError(f"Unsupported database URL {db_url!r}; expected sqlite:///...")
    if not parsed.path:
        raise ValueError(f"Could not determine database path from {db_url!r}")

    path = parsed.path.lstrip("/")
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_bool(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"true", "t", "1", "yes"}:
            return 1
        if lowered in {"false", "f", "0", "no"}:
            return 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    return None


def coerce_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def build_row(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    """Convert a YC company dict into an ordered tuple for SQLite insertion."""

    normalized: Dict[str, Any] = {}
    for column in COLUMN_ORDER:
        raw = entry.get(column)
        if column in INTEGER_FIELDS:
            normalized[column] = coerce_int(raw)
        elif column in BOOLEAN_FIELDS:
            normalized[column] = coerce_bool(raw)
        elif column in JSON_FIELDS:
            normalized[column] = coerce_json(raw)
        else:
            normalized[column] = raw
    return tuple(normalized[column] for column in COLUMN_ORDER)


def insert_rows(connection: sqlite3.Connection, rows: Sequence[Tuple[Any, ...]]) -> None:
    placeholders = ",".join(["?"] * len(COLUMN_ORDER))
    columns = ",".join(COLUMN_ORDER)
    query = f"INSERT INTO yc_companies ({columns}) VALUES ({placeholders})"
    connection.executemany(query, rows)


def replace_companies(records: Iterable[Dict[str, Any]], database_url: str | None = None) -> int:
    """Replace all YC company rows in SQLite with the provided records."""

    db_path = resolve_database_path(database_url)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(CREATE_TABLE_SQL)
        connection.execute("DELETE FROM yc_companies")

        buffer: List[Tuple[Any, ...]] = []
        inserted = 0
        for record in records:
            buffer.append(build_row(record))
            if len(buffer) >= 500:
                insert_rows(connection, buffer)
                inserted += len(buffer)
                buffer.clear()
        if buffer:
            insert_rows(connection, buffer)
            inserted += len(buffer)

        connection.commit()
        return inserted
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump YC OSS API companies to JSONL and SQLite")
    parser.add_argument(
        "--out",
        default=DEFAULT_JSONL,
        help=f"Path for debugging JSONL dump (default: {DEFAULT_JSONL})",
    )
    parser.add_argument(
        "--skip-jsonl",
        action="store_true",
        help="Skip writing the debugging JSONL file",
    )
    parser.add_argument(
        "--from-jsonl",
        help="Load companies from an existing JSONL file instead of fetching from the API",
    )
    parser.add_argument(
        "--also",
        nargs="*",
        default=[],
        help=f"Optional additional company lists to save (choices: {', '.join(sorted(COMPANY_SOURCES.keys() - {'all'}))})",
    )
    parser.add_argument(
        "--save-meta",
        action="store_true",
        help="Also save meta.json next to the JSONL output for provenance",
    )
    parser.add_argument(
        "--sqlite-url",
        default=None,
        help=f"Optional DATABASE_URL override (defaults to env/DATABASE_URL or {DEFAULT_SQLITE_URL})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N companies (applies to the primary list)",
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")

    if args.from_jsonl:
        jsonl_path = Path(args.from_jsonl)
        if not jsonl_path.exists():
            raise FileNotFoundError(f"Could not find JSONL input at {jsonl_path}")
        all_companies = load_jsonl(jsonl_path)
        if args.limit is not None:
            original_count = len(all_companies)
            all_companies = all_companies[: args.limit]
            print(
                f"Applied limit: taking first {len(all_companies):,} of {original_count:,} companies from {jsonl_path}")
        meta = None
        print(f"Loaded {len(all_companies):,} companies from {jsonl_path}")
    else:
        jsonl_path = Path(args.out)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        meta = None
        try:
            meta = fetch_json(META_URL)
        except Exception as exc:  # pragma: no cover - network failure path
            print(f"Warning: failed to fetch meta.json: {exc}", file=sys.stderr)

        all_url = COMPANY_SOURCES["all"]
        print(f"Fetching {all_url} ...")
        all_companies = fetch_json(all_url)
        if not isinstance(all_companies, list):
            raise RuntimeError("Expected a JSON array for companies")

        if args.limit is not None:
            original_count = len(all_companies)
            all_companies = all_companies[: args.limit]
            print(f"Applied limit: taking first {len(all_companies):,} of {original_count:,} fetched companies")

        if not args.skip_jsonl:
            write_jsonl(all_companies, jsonl_path)
            print(f"Wrote {len(all_companies):,} companies to {jsonl_path}")
        else:
            print("Skipping JSONL dump per --skip-jsonl")

        if meta and args.save_meta:
            meta_path = jsonl_path.with_suffix(".meta.json")
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Saved meta to {meta_path}")

        for key in args.also:
            if key not in COMPANY_SOURCES:
                print(
                    f"Skipping unknown list '{key}'. Valid options: {', '.join(COMPANY_SOURCES.keys())}",
                    file=sys.stderr,
                )
                continue
            url = COMPANY_SOURCES[key]
            try:
                print(f"Fetching {url} ...")
                subset = fetch_json(url)
                if not isinstance(subset, list):
                    raise RuntimeError(f"Expected a JSON array for {key}")
                subset_path = jsonl_path.with_name(f"{jsonl_path.stem}.{key}.jsonl")
                write_jsonl(subset, subset_path)
                print(f"Wrote {len(subset):,} records to {subset_path}")
            except Exception as exc:  # pragma: no cover - network failure path
                print(f"Warning: failed to fetch/write '{key}': {exc}", file=sys.stderr)

        if meta:
            last_updated = meta.get("lastUpdated") or meta.get("last_updated")
            companies_count = meta.get("companies")
            print(f"Provenance: meta lastUpdated={last_updated!r}, companies={companies_count!r}")

    inserted = replace_companies(all_companies, database_url=args.sqlite_url)
    db_path = resolve_database_path(args.sqlite_url)
    print(f"Synced {inserted:,} companies into SQLite at {db_path}")


if __name__ == "__main__":
    main()
