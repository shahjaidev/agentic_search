#!/usr/bin/env python3
"""
Parallel enrichment pipeline for YC startup records.

Given an existing SQLite database produced by ``yc_loader.py`` (or compatible
schema), this script runs a Gemini-powered enrichment task for each startup and
writes the results back into the ``startups`` table.

Usage example::

    python yc_enrich.py \
        --db /Users/jaidevshah/agentic_search/data/yc_db.db \
        --attribute founders_summary \
        --query "Summarise the founding team and notable milestones" \
        --sources-column founders_sources \
        --max-workers 6 \
        --limit 100
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

MODEL_NAME = "gemini-2.5-flash-lite"
DEFAULT_MAX_WORKERS = 4
VALID_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def fetch_rows(
    conn: sqlite3.Connection,
    table: str,
    attribute: str,
    limit: Optional[int],
    force: bool,
) -> list[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    if force:
        query = f"SELECT * FROM {table} ORDER BY id"
        params: tuple[Any, ...] = ()
    else:
        query = (
            f"SELECT * FROM {table} "
            f"WHERE \"{attribute}\" IS NULL OR \"{attribute}\" = '' ORDER BY id"
        )
        params = ()
    if limit is not None:
        query += " LIMIT ?"
        params = params + (limit,)
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def build_prompt(row: Dict[str, Any], enrichment_query: str, attribute: str) -> str:
    row_json = json.dumps(row, ensure_ascii=False)
    template = {
        attribute: "",
        "sources": ["https://"],
        "confidence": "medium",
        "notes": "",
    }
    return (
        "You are an enrichment agent helping populate structured attributes for startup records.\n"
        "You MUST ground your findings with reputable sources.\n"
        "Task: {task}\n"
        "For the startup record below, produce the requested attribute.\n"
        "Existing row data (JSON): {row}\n"
        "Return ONLY valid JSON with this structure: {template}\n"
        "Rules:\n"
        "- Fill the '{attribute}' field with the best available answer or leave it as an empty string if truly unavailable.\n"
        "- Provide at least one HTTPS source URL in the 'sources' array.\n"
        "- Set 'confidence' to high, medium, or low.\n"
        "- Use 'notes' for any clarifications or reasoning.\n"
        "- Do not invent data; prefer admitting uncertainty.\n"
    ).format(task=enrichment_query, row=row_json, template=json.dumps(template), attribute=attribute)


def join_candidate_text(response: Any) -> str:
    fragments: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                fragments.append(text)
    return "\n".join(fragment.strip() for fragment in fragments if fragment).strip()


def call_model(api_key: str, prompt: str, temperature: float, use_grounding: bool) -> Dict[str, Any]:
    client = genai.Client(api_key=api_key)
    tools = [types.Tool(google_search=types.GoogleSearch())] if use_grounding else None
    config = types.GenerateContentConfig(
        tools=tools,
        temperature=temperature,
    )
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
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model response was not valid JSON: {payload}") from exc


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
        params: list[Any] = [value or ""]
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


def worker(
    task_queue: "queue.Queue[EnrichmentTask | None]",
    db_path: Path,
    table: str,
    attribute: str,
    enrichment_query: str,
    api_key: str,
    temperature: float,
    use_grounding: bool,
    sources_column: Optional[str],
    notes_column: Optional[str],
    raw_column: Optional[str],
    progress: Dict[str, int],
    progress_lock: threading.Lock,
) -> None:
    while True:
        task = task_queue.get()
        if task is None:  # sentinel
            task_queue.task_done()
            break
        row_id = task.row_id
        row = task.payload
        prompt = build_prompt(row, enrichment_query, attribute)
        try:
            result = call_model(api_key, prompt, temperature, use_grounding)
            value_obj = result.get(attribute)
            if isinstance(value_obj, str):
                value = value_obj
            elif value_obj is None:
                value = ""
            else:
                value = json.dumps(value_obj, ensure_ascii=False)

            sources = result.get("sources")
            notes_obj = result.get("notes")
            if isinstance(notes_obj, str) or notes_obj is None:
                notes = notes_obj
            else:
                notes = json.dumps(notes_obj, ensure_ascii=False)
            update_row(
                db_path=db_path,
                table=table,
                attribute=attribute,
                row_id=row_id,
                value=value,
                sources_column=sources_column,
                sources=sources if isinstance(sources, list) else None,
                notes_column=notes_column,
                notes=notes,
                raw_column=raw_column,
                raw_json=result,
            )
            with progress_lock:
                progress["success"] += 1
        except Exception as exc:  # noqa: BLE001
            with progress_lock:
                progress["failed"] += 1
            print(f"[worker] Row {row_id} failed: {exc}", flush=True)
        finally:
            with progress_lock:
                progress["processed"] += 1
            task_queue.task_done()
            time.sleep(0.1)  # light throttling to respect rate limits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich YC startups using Gemini")
    parser.add_argument("--db", required=True, help="Path to the SQLite database (e.g. data/yc_db.db)")
    parser.add_argument("--attribute", required=True, help="Column name to populate with the enriched value")
    parser.add_argument("--query", required=True, help="Instruction for the enrichment agents")
    parser.add_argument("--sources-column", help="Optional column to store JSON array of sources")
    parser.add_argument("--notes-column", help="Optional column to store freeform notes")
    parser.add_argument("--raw-column", help="Optional column to store the full JSON response")
    parser.add_argument("--limit", type=int, help="Process only the first N applicable startups")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS, help="Number of parallel Gemini calls")
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")

    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be a positive integer when provided")

    api_key = load_api_key()

    attribute = validate_column_name(args.attribute.strip(), "--attribute")
    sources_column = validate_column_name(args.sources_column.strip(), "--sources-column") if args.sources_column else None
    notes_column = validate_column_name(args.notes_column.strip(), "--notes-column") if args.notes_column else None
    raw_column = validate_column_name(args.raw_column.strip(), "--raw-column") if args.raw_column else None


    with sqlite3.connect(db_path) as conn:
        ensure_column(conn, attribute)
        if sources_column:
            ensure_column(conn, sources_column)
        if notes_column:
            ensure_column(conn, notes_column)
        if raw_column:
            ensure_column(conn, raw_column)
        rows = fetch_rows(conn, attribute, args.limit, args.force)

    if not rows:
        print("No rows require enrichment. Nothing to do.")
        return

    print(f"Queued {len(rows):,} startup rows for enrichment with attribute '{attribute}'.")

    task_queue: "queue.Queue[EnrichmentTask | None]" = queue.Queue()
    progress = {"processed": 0, "success": 0, "failed": 0}
    progress_lock = threading.Lock()

    workers: list[threading.Thread] = []
    for _ in range(max(1, args.max_workers)):
        thread = threading.Thread(
            target=worker,
            kwargs={
                "task_queue": task_queue,
                "db_path": db_path,
                "table": table,
                "attribute": attribute,
                "enrichment_query": args.query,
                "api_key": api_key,
                "temperature": args.temperature,
                "use_grounding": args.use_grounding,
                "sources_column": sources_column,
                "notes_column": notes_column,
                "raw_column": raw_column,
                "progress": progress,
                "progress_lock": progress_lock,
            },
            daemon=True,
        )
        thread.start()
        workers.append(thread)

    for row in rows:
        task_queue.put(EnrichmentTask(row_id=row["id"], payload=row))

    # send sentinel to each worker
    for _ in workers:
        task_queue.put(None)

    task_queue.join()

    for thread in workers:
        thread.join()

    print(
        "Completed enrichment: {processed:,} processed, {success:,} succeeded, {failed:,} failed.".format(
            processed=progress["processed"], success=progress["success"], failed=progress["failed"]
        )
    )


if __name__ == "__main__":
    main()
