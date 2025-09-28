#!/usr/bin/env python3
"""Batch enrichment pipeline for YC startup records using Gemini.

This variant processes companies in fixed-size batches (default: 10 rows per
model call) to improve throughput while updating the source SQLite table and
optionally writing a JSONL audit log.

python yc_enrich_batch.py \
    --db data/yc_companies.db \
    --attribute product_vertical \
    --query "Classify this company’s product vertical (e.g., robotics, video generation, social media, fintech, healthtech). Return one clear label." \
    --sources-column product_vertical_sources \
    --notes-column product_vertical_notes \
    --where "batch IS NOT NULL AND CAST(substr(batch, -4) AS INTEGER) >= 2024" \
    --batch-size 10 \
    --max-workers 16

"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import threading
import time
import re

from google import genai
from google.genai import types

MODEL_NAME = "gemini-2.5-flash-lite"
DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_WORKERS = 4
DEFAULT_JSONL_LOG = "/Users/jaidevshah/agentic_search/data/yc_enriched_jsonl.jsonl"
DEFAULT_WHERE_CLAUSE = "batch IS NOT NULL AND CAST(substr(batch, -4) AS INTEGER) >= 2023"
DEFAULT_CLEAR_OUTSIDE_WHERE = True
VALID_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_api_key() -> str:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set GOOGLE_API_KEY (preferred) or GEMINI_API_KEY before running enrichment."
        )
    return api_key.strip()


def ensure_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = {row[1] for row in cursor.fetchall()}
    if column in columns:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN \"{column}\" TEXT")
    conn.commit()


def validate_column_name(column: str, label: str) -> str:
    if not VALID_COLUMN_RE.fullmatch(column):
        raise ValueError(f"{label} must be a valid SQL column identifier: {column!r}")
    return column


def normalise_option_list(
    values: Optional[List[str]],
    count: int,
    label: str,
    parser: argparse.ArgumentParser,
) -> List[Optional[str]]:
    if not values:
        return [None] * count
    cleaned = [value.strip() for value in values]
    if len(cleaned) == 1 and count > 1:
        return cleaned * count
    if len(cleaned) != count:
        parser.error(f"{label} must be provided once or {count} times to match --attribute")
    return cleaned


def append_jsonl(jsonl_path: Optional[Path], lock: threading.Lock, record: Dict[str, Any]) -> None:
    if jsonl_path is None:
        return
    with lock:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def _clear_attribute_outside_where(
    conn: sqlite3.Connection,
    table: str,
    attribute: str,
    where_clause: str,
    sources_column: Optional[str],
    notes_column: Optional[str],
    raw_column: Optional[str],
) -> int:
    assignments = [f"\"{attribute}\" = ''"]
    if sources_column:
        assignments.append(f"\"{sources_column}\" = '[]'")
    if notes_column:
        assignments.append(f"\"{notes_column}\" = ''")
    if raw_column:
        assignments.append(f'"{raw_column}" = NULL')
    clause = (
        f"UPDATE {table} SET {', '.join(assignments)} "
        f"WHERE (CASE WHEN ({where_clause}) THEN 1 ELSE 0 END) = 0"
    )
    cursor = conn.execute(clause)
    conn.commit()
    return cursor.rowcount if cursor.rowcount is not None else 0


def fetch_rows(
    conn: sqlite3.Connection,
    table: str,
    attribute: str,
    limit: Optional[int],
    force: bool,
    where_clause: Optional[str],
) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    conditions: List[str] = []
    if where_clause:
        conditions.append(f"({where_clause})")
    if not force:
        conditions.append(f"(\"{attribute}\" IS NULL OR \"{attribute}\" = '')")
    where_sql = ""
    if conditions:
        where_sql = " WHERE " + " AND ".join(conditions)
    query = f"SELECT * FROM {table}{where_sql} ORDER BY id"
    params: tuple[Any, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = params + (limit,)
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def chunked(items: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_batch_prompt(
    rows: List[Dict[str, Any]],
    attribute: str,
    enrichment_query: str,
) -> str:
    template = {
        "row_id": 0,
        attribute: "",
        "sources": ["https://"],
        "confidence": "medium",
        "notes": "",
    }
    payload = []
    for row in rows:
        payload.append(
            {
                "row_id": row["id"],
                "company_name": row.get("company_name") or row.get("name"),
                "website": row.get("website"),
                "batch": row.get("batch"),
                "record": row,
            }
        )
    instruction = (
        "You enrich YC startup records. For each input row, respond with an object "
        "matching the provided schema.\n"
        "Rules:\n"
        "- Produce a JSON array with one object per input row.\n"
        "- Copy the integer `row_id` exactly so we can map results back.\n"
        "- Populate the '{attribute}' field as instructed: {query}.\n"
        "- `sources` must only contain verified HTTPS URLs (<= 5).\n"
        "- `confidence` must be one of: high, medium, low.\n"
        "- `notes` is optional context; use an empty string if not needed.\n"
        "- Return STRICT JSON with no extra commentary.\n"
    ).format(attribute=attribute, query=enrichment_query)
    return (
        f"{instruction}\n"
        f"Expected schema: {json.dumps(template, ensure_ascii=False)}\n"
        f"Input rows: {json.dumps(payload, ensure_ascii=False)}"
    )


def join_candidate_text(response: Any) -> str:
    fragments: List[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                fragments.append(text)
    return "\n".join(fragment.strip() for fragment in fragments if fragment).strip()


def _strip_code_fence(payload: str) -> str:
    stripped = payload.strip()
    if stripped.startswith("```"):
        stripped = stripped[3:]
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.lstrip()
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    return stripped


def _extract_json_payload(payload: str) -> str:
    stripped = _strip_code_fence(payload)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end != -1 and end > start:
            candidate = stripped[start : end + 1].strip()
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                continue
    return stripped


def call_model(
    api_key: str,
    prompt: str,
    temperature: float,
    use_grounding: bool,
) -> List[Dict[str, Any]]:
    client = genai.Client(api_key=api_key)
    tools = [types.Tool(google_search=types.GoogleSearch())] if use_grounding else None
    config = types.GenerateContentConfig(tools=tools, temperature=temperature)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=config,
    )
    payload = (getattr(response, "text", "") or "").strip()
    if not payload:
        payload = join_candidate_text(response)
    if not payload:
        raise ValueError("Model returned no text payload")
    cleaned = _extract_json_payload(payload)
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("Expected model to return a JSON array")
    return data


def update_row(
    db_path: Path,
    table: str,
    attribute: str,
    row_id: int,
    value: Optional[str],
    sources_column: Optional[str],
    sources: Optional[Iterable[str]],
    notes_column: Optional[str],
    notes: Optional[str],
    raw_column: Optional[str],
    raw_json: Dict[str, Any],
) -> None:
    connection = sqlite3.connect(db_path)
    try:
        assignments = [f'"{attribute}" = ?']
        params: List[Any] = [value or ""]
        if sources_column:
            assignments.append(f'"{sources_column}" = ?')
            params.append(json.dumps(list(sources or []), ensure_ascii=False))
        if notes_column:
            assignments.append(f'"{notes_column}" = ?')
            params.append(notes or "")
        if raw_column:
            assignments.append(f'"{raw_column}" = ?')
            params.append(json.dumps(raw_json, ensure_ascii=False))
        params.append(row_id)
        statement = f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?"
        connection.execute(statement, params)
        connection.commit()
    finally:
        connection.close()


def process_batch(
    batch_rows: List[Dict[str, Any]],
    attribute: str,
    query: str,
    api_key: str,
    temperature: float,
    use_grounding: bool,
    db_path: Path,
    table: str,
    sources_column: Optional[str],
    notes_column: Optional[str],
    raw_column: Optional[str],
    jsonl_path: Optional[Path],
    jsonl_lock: threading.Lock,
) -> Dict[str, int]:
    processed = len(batch_rows)
    success = 0
    failed = 0

    prompt = build_batch_prompt(batch_rows, attribute, query)
    try:
        results = call_model(api_key, prompt, temperature, use_grounding)
        mapping: Dict[int, Dict[str, Any]] = {}
        for item in results:
            if not isinstance(item, dict) or "row_id" not in item:
                raise ValueError("Each result must be an object containing 'row_id'.")
            mapping[int(item["row_id"])] = item

        expected_ids = {int(row["id"]) for row in batch_rows}
        if set(mapping.keys()) != expected_ids:
            missing = expected_ids - set(mapping.keys())
            extra = set(mapping.keys()) - expected_ids
            raise ValueError(
                f"Model response mismatch; missing: {sorted(missing)}, extra: {sorted(extra)}"
            )

        timestamp = time.time()
        for row in batch_rows:
            row_id = int(row["id"])
            result = mapping[row_id]
            value_obj = result.get(attribute)
            if isinstance(value_obj, str):
                value = value_obj
            elif value_obj is None:
                value = ""
            else:
                value = json.dumps(value_obj, ensure_ascii=False)

            sources = result.get("sources") if isinstance(result.get("sources"), list) else None
            notes_obj = result.get("notes")
            notes = notes_obj if isinstance(notes_obj, str) else json.dumps(notes_obj, ensure_ascii=False) if notes_obj not in (None, "") else ""
            raw_json = result

            update_row(
                db_path=db_path,
                table=table,
                attribute=attribute,
                row_id=row_id,
                value=value,
                sources_column=sources_column,
                sources=sources,
                notes_column=notes_column,
                notes=notes,
                raw_column=raw_column,
                raw_json=raw_json,
            )

            log_record = dict(row)
            log_record[attribute] = value
            if sources_column and sources is not None:
                log_record[sources_column] = sources
            if notes_column:
                log_record[notes_column] = notes
            if raw_column:
                log_record[raw_column] = raw_json
            log_record.setdefault("_batch_timestamp", timestamp)
            append_jsonl(jsonl_path, jsonl_lock, log_record)
            success += 1
    except Exception as exc:  # noqa: BLE001
        failed = processed
        for row in batch_rows:
            error_record = dict(row)
            error_record.setdefault(attribute, row.get(attribute, ""))
            error_record["_enrichment_error"] = str(exc)
            append_jsonl(jsonl_path, jsonl_lock, error_record)
    return {"processed": processed, "success": success, "failed": failed}


def run_enrichment_task(
    *,
    db_path: Path,
    table: str,
    attribute: str,
    query: str,
    sources_column: Optional[str],
    notes_column: Optional[str],
    raw_column: Optional[str],
    limit: Optional[int],
    force: bool,
    where_clause: Optional[str],
    clear_outside_where: bool,
    batch_size: int,
    max_workers: int,
    temperature: float,
    use_grounding: bool,
    api_key: str,
    jsonl_path: Optional[Path],
    jsonl_lock: threading.Lock,
) -> None:
    with sqlite3.connect(db_path) as conn:
        ensure_column(conn, table, attribute)
        if sources_column:
            ensure_column(conn, table, sources_column)
        if notes_column:
            ensure_column(conn, table, notes_column)
        if raw_column:
            ensure_column(conn, table, raw_column)
        if where_clause and clear_outside_where:
            cleared = _clear_attribute_outside_where(
                conn,
                table,
                attribute,
                where_clause,
                sources_column,
                notes_column,
                raw_column,
            )
            if cleared:
                print(
                    f"Blanked '{attribute}' for {cleared} rows outside the WHERE filter before enrichment."
                )
        rows = fetch_rows(conn, table, attribute, limit, force, where_clause)

    if not rows:
        print(f"No rows require enrichment for column '{attribute}'. Skipping.")
        return

    batches = chunked(rows, batch_size)
    print(
        f"Queued {len(rows):,} rows across {len(batches)} batches (size {batch_size}) "
        f"for enrichment of column '{attribute}'."
    )

    progress = {"processed": 0, "success": 0, "failed": 0}
    progress_lock = threading.Lock()

    def submit_batch(batch_rows: List[Dict[str, Any]]):
        result = process_batch(
            batch_rows=batch_rows,
            attribute=attribute,
            query=query,
            api_key=api_key,
            temperature=temperature,
            use_grounding=use_grounding,
            db_path=db_path,
            table=table,
            sources_column=sources_column,
            notes_column=notes_column,
            raw_column=raw_column,
            jsonl_path=jsonl_path,
            jsonl_lock=jsonl_lock,
        )
        with progress_lock:
            for key, value in result.items():
                progress[key] += value
        if result["failed"]:
            print(
                f"[batch] Failed rows {', '.join(str(row['id']) for row in batch_rows)}"  # noqa: RUF001
            )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(submit_batch, batch) for batch in batches]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[batch] Unexpected error: {exc}")

    print(
        "Completed enrichment for '{attribute}': {processed:,} processed, {success:,} succeeded, {failed:,} failed.".format(
            attribute=attribute,
            processed=progress["processed"],
            success=progress["success"],
            failed=progress["failed"],
        )
    )


def parse_args() -> tuple[argparse.Namespace, argparse.ArgumentParser]:
    parser = argparse.ArgumentParser(description="Batch enrich YC startups using Gemini")
    parser.add_argument("--db", required=True, help="Path to the SQLite database (e.g. data/yc_db.db)")
    parser.add_argument(
        "--attribute",
        action="append",
        required=True,
        help="Column name to populate with the enriched value (repeatable)",
    )
    parser.add_argument(
        "--query",
        action="append",
        required=True,
        help="Instruction for the enrichment agents (repeat to match attributes)",
    )
    parser.add_argument(
        "--table",
        default="yc_companies",
        help="Name of the table containing startup records (default: yc_companies)",
    )
    parser.add_argument(
        "--sources-column",
        action="append",
        help="Optional column to store JSON array of sources (repeat or provide once)",
    )
    parser.add_argument(
        "--notes-column",
        action="append",
        help="Optional column to store freeform notes (repeat or provide once)",
    )
    parser.add_argument(
        "--raw-column",
        action="append",
        help="Optional column to store the full JSON response (repeat or provide once)",
    )
    parser.add_argument(
        "--jsonl-out",
        default=DEFAULT_JSONL_LOG,
        help=(
            "Path to append enrichment logs as JSON Lines (use '-' to disable; default: "
            f"{DEFAULT_JSONL_LOG})"
        ),
    )
    parser.add_argument(
        "--where",
        default=DEFAULT_WHERE_CLAUSE,
        help=(
            "SQL WHERE clause applied before enrichment (default filters for batches from 2023 onwards). "
            "Pass an empty string to disable."
        ),
    )
    parser.add_argument(
        "--no-clear-outside-where",
        dest="clear_outside_where",
        action="store_false",
        help="Do not blank the attribute for rows that fail the WHERE clause filter.",
    )
    parser.set_defaults(clear_outside_where=DEFAULT_CLEAR_OUTSIDE_WHERE)
    parser.add_argument("--limit", type=int, help="Process only the first N applicable startups")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of rows to send per Gemini request (default: 10)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="Number of concurrent Gemini calls (default: 4)",
    )
    parser.add_argument("--temperature", type=float, default=0.0, help="Model temperature")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-enrich rows even if the attribute already has a value",
    )
    parser.add_argument(
        "--no-grounding",
        dest="use_grounding",
        action="store_false",
        help="Disable Google Search grounding (enabled by default)",
    )
    parser.set_defaults(use_grounding=True)
    args = parser.parse_args()
    return args, parser


def main() -> None:
    args, parser = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be a positive integer when provided")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be a positive integer")
    if args.max_workers <= 0:
        raise ValueError("--max-workers must be a positive integer")

    api_key = load_api_key()
    table = validate_column_name(args.table.strip(), "--table")

    attributes = [validate_column_name(attr.strip(), "--attribute") for attr in args.attribute]
    attr_count = len(attributes)

    queries_raw = [q.strip() for q in args.query]
    if len(queries_raw) == 1 and attr_count > 1:
        queries = queries_raw * attr_count
    elif len(queries_raw) != attr_count:
        parser.error("--query must be provided once or the same number of times as --attribute")
    else:
        queries = queries_raw

    sources_columns = normalise_option_list(args.sources_column, attr_count, "--sources-column", parser)
    notes_columns = normalise_option_list(args.notes_column, attr_count, "--notes-column", parser)
    raw_columns = normalise_option_list(args.raw_column, attr_count, "--raw-column", parser)

    sources_columns = [validate_column_name(col, "--sources-column") if col else None for col in sources_columns]
    notes_columns = [validate_column_name(col, "--notes-column") if col else None for col in notes_columns]
    raw_columns = [validate_column_name(col, "--raw-column") if col else None for col in raw_columns]

    jsonl_path = None if args.jsonl_out.strip() == "-" else Path(args.jsonl_out.strip())
    jsonl_lock = threading.Lock()

    where_clause_raw = (args.where or "").strip()
    where_clause = where_clause_raw or None
    if where_clause:
        print(f"Applying WHERE filter: {where_clause}")
    else:
        print("No WHERE filter applied; processing all rows allowed by other flags.")

    for attribute, query, sources_column, notes_column, raw_column in zip(
        attributes, queries, sources_columns, notes_columns, raw_columns
    ):
        run_enrichment_task(
            db_path=db_path,
            table=table,
            attribute=attribute,
            query=query,
            sources_column=sources_column,
            notes_column=notes_column,
            raw_column=raw_column,
            limit=args.limit,
            force=args.force,
            where_clause=where_clause,
            clear_outside_where=args.clear_outside_where,
            batch_size=args.batch_size,
            max_workers=args.max_workers,
            temperature=args.temperature,
            use_grounding=args.use_grounding,
            api_key=api_key,
            jsonl_path=jsonl_path,
            jsonl_lock=jsonl_lock,
        )


if __name__ == "__main__":
    main()
