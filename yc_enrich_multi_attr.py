#!/usr/bin/env python3
"""Enrich multiple YC startup attributes per row using a single Gemini call.

Example::

    python yc_enrich_multi_attr.py \
        --db data/yc_companies.db \
        --attribute product_vertical \
        --attribute open_roles \
        --attribute latest_fundraising_amount \
        --attribute latest_fundraising_date \
        --attribute investors \
        --query "Classify this company’s product vertical (e.g., robotics, video generation, social media, fintech, healthtech). Return one clear label." \
        --query "List the active job openings, using the startup’s careers page or recent public postings (e.g., Hacker News 'Who’s Hiring?'). Return a comma-separated string; use an empty string if nothing is verifiable." \
        --query "Report the most recent fundraising amount (USD, integer). Use several searches, blogs, tweets, crunchbase, etc. Only if at the end it is unknown, return an empty string." \
        --query "Provide the date of the most recent fundraising event in ISO format (YYYY-MM-DD). Use several searches, blogs, tweets, crunchbase, etc. If unknown, return an empty string." \
        --query "List the confirmed investors in the most recent round as a JSON array of strings (e.g., [\"Sequoia Capital\", \"YC Continuity\"]). Return an empty array if nothing is verifiable." \
        --sources-column product_vertical_sources \
        --sources-column open_roles_sources \
        --sources-column latest_fundraising_amount_sources \
        --sources-column latest_fundraising_date_sources \
        --sources-column investors_sources \
        --notes-column product_vertical_notes \
        --notes-column open_roles_notes \
        --notes-column latest_fundraising_amount_notes \
        --notes-column latest_fundraising_date_notes \
        --notes-column investors_notes \
        --where "batch IS NOT NULL AND CAST(substr(batch, -4) AS INTEGER) >= 2025" \
        --max-workers 32
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
import re

from google import genai
from google.genai import types

MODEL_NAME = "gemini-2.5-flash"
DEFAULT_MAX_WORKERS = 10
DEFAULT_JSONL_LOG = "/Users/jaidevshah/agentic_search/data/yc_enriched_jsonl.jsonl"
DEFAULT_WHERE_CLAUSE = "batch IS NOT NULL AND CAST(substr(batch, -4) AS INTEGER) >= 2023"
VALID_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class AttributeSpec:
    name: str
    query: str
    sources_column: Optional[str]
    notes_column: Optional[str]
    raw_column: Optional[str]


@dataclass
class EnrichmentTask:
    row_id: int
    payload: Dict[str, Any]


def load_api_key() -> str:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set GOOGLE_API_KEY (preferred) or GEMINI_API_KEY in your environment before running enrichment."
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
        raise ValueError(f"{label} must be a valid SQL column identifier (letters, numbers, underscore): {column!r}")
    return column


def normalise_option_list(
    values: Optional[list[str]],
    count: int,
    label: str,
    parser: argparse.ArgumentParser,
) -> list[Optional[str]]:
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


def fetch_rows(
    conn: sqlite3.Connection,
    table: str,
    attribute: str,
    limit: Optional[int],
    force: bool,
    where_clause: Optional[str],
) -> list[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    conditions: list[str] = []
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


def join_candidate_text(response: Any) -> str:
    fragments: list[str] = []
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
) -> Dict[str, Any]:
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
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response was not valid JSON: {payload}") from exc


def build_prompt(row: Dict[str, Any], specs: Iterable[AttributeSpec]) -> str:
    tasks = []
    for spec in specs:
        task = {
            "attribute": spec.name,
            "instruction": spec.query,
            "output_keys": {
                "value": "string | number | array (use empty string/array when unknown)",
                "sources": "array of verified HTTPS URLs (<=5)",
                "notes": "optional string explaining the decision",
            },
        }
        tasks.append(task)
    template = {
        "row_id": 0,
        "attributes": {
            spec.name: {
                "value": "",
                "sources": ["https://"],
                "notes": "",
            }
            for spec in specs
        },
    }
    return (
        "You enrich YC startup records. For the provided row, answer every attribute using the "
        "specific instructions.\n"
        "Rules:\n"
        "- Return a SINGLE JSON object matching the schema below.\n"
        "- Copy the integer row_id exactly from the input.\n"
        "- For each attribute, fill `value`, `sources`, and `notes`.\n"
        "- Use empty strings/arrays when information cannot be verified.\n"
        "- NEVER wrap the JSON in code fences or prose.\n\n"
        f"Attribute tasks: {json.dumps(tasks, ensure_ascii=False)}\n"
        f"Output schema: {json.dumps(template, ensure_ascii=False)}\n"
        f"Startup row JSON: {json.dumps(row, ensure_ascii=False)}"
    )


def _serialise_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _extract_assignment(spec: AttributeSpec, result: Dict[str, Any]) -> tuple[list[str], list[Any]]:
    value = _serialise_value(result.get("value"))
    sources = result.get("sources") if isinstance(result.get("sources"), list) else None
    notes = result.get("notes") if isinstance(result.get("notes"), str) else (
        json.dumps(result.get("notes"), ensure_ascii=False)
        if result.get("notes") not in (None, "")
        else ""
    )

    assignments = [f'"{spec.name}" = ?']
    params: list[Any] = [value]
    if spec.sources_column:
        assignments.append(f'"{spec.sources_column}" = ?')
        params.append(json.dumps(list(sources or []), ensure_ascii=False))
    if spec.notes_column:
        assignments.append(f'"{spec.notes_column}" = ?')
        params.append(notes or "")
    if spec.raw_column:
        assignments.append(f'"{spec.raw_column}" = ?')
        params.append(json.dumps(result, ensure_ascii=False))
    return assignments, params


def worker(
    task_queue: "queue.Queue[EnrichmentTask | None]",
    db_path: Path,
    table: str,
    specs: list[AttributeSpec],
    api_key: str,
    temperature: float,
    use_grounding: bool,
    progress: Dict[str, int],
    progress_lock: threading.Lock,
    jsonl_path: Optional[Path],
    jsonl_lock: threading.Lock,
    stop_event: threading.Event,
) -> None:
    connection = sqlite3.connect(db_path)
    try:
        while True:
            if stop_event.is_set():
                break
            try:
                task = task_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if task is None:
                task_queue.task_done()
                break
            row = task.payload
            prompt = build_prompt(row, specs)
            try:
                response = call_model(api_key, prompt, temperature, use_grounding)
                attributes = response.get("attributes")
                if not isinstance(attributes, dict):
                    raise ValueError("Model response missing 'attributes' object")

                assignments: list[str] = []
                params: list[Any] = []
                log_record_payload: Dict[str, Any] = {}

                for spec in specs:
                    result = attributes.get(spec.name)
                    if not isinstance(result, dict):
                        raise ValueError(f"Model response missing data for attribute '{spec.name}'")
                    spec_assignments, spec_params = _extract_assignment(spec, result)
                    assignments.extend(spec_assignments)
                    params.extend(spec_params)
                    log_record_payload[spec.name] = result

                params.append(task.row_id)
                connection.execute(
                    f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?",
                    params,
                )
                connection.commit()

                with progress_lock:
                    progress["success"] += 1
                log_record = dict(row)
                log_record["multi_attribute_enrichment"] = log_record_payload
                append_jsonl(jsonl_path, jsonl_lock, log_record)
            except Exception as exc:  # noqa: BLE001
                with progress_lock:
                    progress["failed"] += 1
                error_record = dict(row)
                error_record["_enrichment_error"] = str(exc)
                append_jsonl(jsonl_path, jsonl_lock, error_record)
            finally:
                with progress_lock:
                    progress["processed"] += 1
                task_queue.task_done()
                time.sleep(0.1)
    finally:
        connection.close()


def run_enrichment_task(
    *,
    db_path: Path,
    table: str,
    specs: list[AttributeSpec],
    limit: Optional[int],
    force: bool,
    where_clause: Optional[str],
    max_workers: int,
    temperature: float,
    use_grounding: bool,
    api_key: str,
    jsonl_path: Optional[Path],
    jsonl_lock: threading.Lock,
    max_wait_seconds: Optional[float],
) -> None:
    primary_attribute = specs[0].name
    with sqlite3.connect(db_path) as conn:
        for spec in specs:
            ensure_column(conn, table, spec.name)
            if spec.sources_column:
                ensure_column(conn, table, spec.sources_column)
            if spec.notes_column:
                ensure_column(conn, table, spec.notes_column)
            if spec.raw_column:
                ensure_column(conn, table, spec.raw_column)
        rows = fetch_rows(conn, table, primary_attribute, limit, force, where_clause)

    if not rows:
        print(f"No rows require enrichment for attribute '{primary_attribute}'. Skipping.")
        return

    print(
        f"Queued {len(rows):,} rows from '{table}' for multi-attribute enrichment of {len(specs)} columns."
    )

    task_queue: "queue.Queue[EnrichmentTask | None]" = queue.Queue()
    progress = {"processed": 0, "success": 0, "failed": 0}
    progress_lock = threading.Lock()
    stop_event = threading.Event()

    workers: list[threading.Thread] = []
    for _ in range(max(1, max_workers)):
        thread = threading.Thread(
            target=worker,
            kwargs={
                "task_queue": task_queue,
                "db_path": db_path,
                "table": table,
                "specs": specs,
                "api_key": api_key,
                "temperature": temperature,
                "use_grounding": use_grounding,
                "progress": progress,
                "progress_lock": progress_lock,
                "jsonl_path": jsonl_path,
                "jsonl_lock": jsonl_lock,
                "stop_event": stop_event,
            },
            daemon=True,
        )
        thread.start()
        workers.append(thread)

    for row in rows:
        task_queue.put(EnrichmentTask(row_id=row["id"], payload=row))

    for _ in workers:
        task_queue.put(None)

    total_rows = len(rows)
    completed = False
    start_time = time.monotonic()
    wait_limit = max_wait_seconds if max_wait_seconds and max_wait_seconds > 0 else None

    while True:
        with progress_lock:
            processed = progress["processed"]
        if processed >= total_rows:
            completed = True
            break
        if wait_limit is not None and (time.monotonic() - start_time) >= wait_limit:
            print(
                "Multi-attribute enrichment exceeded wait limit; continuing with partial results."
            )
            break
        time.sleep(1.0)

    if not completed:
        stop_event.set()
        # Drain any remaining sentinel/task items to unblock workers.
        while True:
            try:
                item = task_queue.get_nowait()
            except queue.Empty:
                break
            else:
                task_queue.task_done()

    else:
        # Ensure all task_done calls accounted for before joining.
        task_queue.join()

    for thread in workers:
        thread.join(timeout=5.0)

    print(
        "Completed multi-attribute enrichment: {processed:,} processed, {success:,} succeeded, {failed:,} failed.".format(
            processed=progress["processed"],
            success=progress["success"],
            failed=progress["failed"],
        )
    )


def parse_args() -> tuple[argparse.Namespace, argparse.ArgumentParser]:
    parser = argparse.ArgumentParser(description="Enrich multiple YC startup attributes per row using Gemini")
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
        help="Instruction for the enrichment agent (repeat to match attributes)",
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
        help="Optional column to store notes (repeat or provide once)",
    )
    parser.add_argument(
        "--raw-column",
        action="append",
        help="Optional column to store the raw model object per attribute (repeat or provide once)",
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
    parser.add_argument("--limit", type=int, help="Process only the first N applicable startups")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help="Number of parallel Gemini calls")
    parser.add_argument("--temperature", type=float, default=0.0, help="Model temperature")
    parser.add_argument(
        "--no-force",
        dest="force",
        action="store_false",
        help="Process only rows where the primary attribute is empty",
    )
    parser.set_defaults(force=True)
    parser.add_argument(
        "--no-grounding",
        dest="use_grounding",
        action="store_false",
        help="Disable Google Search grounding (enabled by default)",
    )
    parser.set_defaults(use_grounding=True)
    parser.add_argument(
        "--max-wait-seconds",
        type=float,
        default=600.0,
        help="Maximum time in seconds to wait for all threads before exiting early (default: 120)",
    )
    args = parser.parse_args()
    return args, parser


def main() -> None:
    args, parser = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be a positive integer when provided")

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

    specs = [
        AttributeSpec(
            name=attr,
            query=query,
            sources_column=sources_col,
            notes_column=notes_col,
            raw_column=raw_col,
        )
        for attr, query, sources_col, notes_col, raw_col in zip(
            attributes, queries, sources_columns, notes_columns, raw_columns
        )
    ]

    primary_attribute = specs[0].name
    jsonl_path = None if args.jsonl_out.strip() == "-" else Path(args.jsonl_out.strip())
    jsonl_lock = threading.Lock()

    where_clause_raw = (args.where or "").strip()
    where_clause = where_clause_raw or None
    if where_clause:
        print(f"Applying WHERE filter: {where_clause}")
    else:
        print("No WHERE filter applied; processing all rows allowed by other flags.")

    run_enrichment_task(
        db_path=db_path,
        table=table,
        specs=specs,
        limit=args.limit,
        force=args.force,
        where_clause=where_clause,
        max_workers=args.max_workers,
        temperature=args.temperature,
        use_grounding=args.use_grounding,
        api_key=api_key,
        jsonl_path=jsonl_path,
        jsonl_lock=jsonl_lock,
        max_wait_seconds=args.max_wait_seconds,
    )


if __name__ == "__main__":
    main()
