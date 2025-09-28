"""Self-contained FastAPI app to inspect SQLite databases with a minimal UI."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, List, Sequence

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parent
ALLOWED_ROOTS = {PROJECT_ROOT, PROJECT_ROOT / "data"}


def _is_within(path: Path, candidate_parent: Path) -> bool:
    try:
        path.relative_to(candidate_parent)
    except ValueError:
        return False
    return True


def _resolve_db_path(raw_path: str) -> Path:
    if not raw_path:
        raise HTTPException(status_code=400, detail="Database path must be provided.")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not any(_is_within(candidate, root.resolve()) for root in ALLOWED_ROOTS):
        raise HTTPException(status_code=403, detail="Database path is outside allowed directories.")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Database file not found.")
    return candidate


def _connect(db_path: Path) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
    except sqlite3.Error as exc:  # defensive, surfaced to client
        raise HTTPException(status_code=500, detail=f"Failed to open database: {exc}")
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_rows(cursor: sqlite3.Cursor, limit: int) -> tuple[List[sqlite3.Row], bool]:
    rows = cursor.fetchmany(limit + 1)
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]
    return rows, truncated


class TableColumn(BaseModel):
    name: str
    type: str = Field(default="")
    notnull: bool
    default: Any = None
    primary_key: bool


class TableSchema(BaseModel):
    name: str
    type: str
    columns: List[TableColumn]


class SchemaResponse(BaseModel):
    database: str
    tables: List[TableSchema]


class QueryRequest(BaseModel):
    db_path: str
    sql: str
    limit: int = Field(default=200, ge=1, le=2000)


class QueryResponse(BaseModel):
    database: str
    sql: str
    columns: List[str]
    rows: List[dict[str, Any]]
    row_count: int
    truncated: bool


app = FastAPI(title="SQLite Explorer", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(
        INDEX_HTML.replace("__PROJECT_ROOT__", str(PROJECT_ROOT))
    )


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/schema", response_model=SchemaResponse)
def get_schema(db_path: str = Query(..., description="Absolute or project-relative path to the SQLite database.")) -> SchemaResponse:
    path = _resolve_db_path(db_path)
    with _connect(path) as conn:
        tables = _load_table_schemas(conn)
    return SchemaResponse(database=str(path), tables=tables)


def _load_table_schemas(conn: sqlite3.Connection) -> List[TableSchema]:
    cursor = conn.execute(
        """
        SELECT name, type
        FROM sqlite_master
        WHERE type IN ('table', 'view')
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    )
    schemas: List[TableSchema] = []
    for row in cursor.fetchall():
        table_name = row["name"]
        table_type = row["type"]
        columns_cursor = conn.execute(f"PRAGMA table_info('{table_name}')")
        columns = [
            TableColumn(
                name=col["name"],
                type=col["type"] or "",
                notnull=bool(col["notnull"]),
                default=col["dflt_value"],
                primary_key=bool(col["pk"]),
            )
            for col in columns_cursor.fetchall()
        ]
        schemas.append(TableSchema(name=table_name, type=table_type, columns=columns))
    return schemas


@app.post("/query", response_model=QueryResponse)
def run_query(request: QueryRequest) -> QueryResponse:
    path = _resolve_db_path(request.db_path)
    sql_statement = request.sql.strip()
    if not sql_statement:
        raise HTTPException(status_code=400, detail="SQL must be provided.")
    sql_statement = _sanitize_sql(sql_statement)

    with _connect(path) as conn:
        try:
            cursor = conn.execute(sql_statement)
        except sqlite3.Error as exc:
            raise HTTPException(status_code=400, detail=f"SQL execution failed: {exc}")
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows, truncated = _fetch_rows(cursor, request.limit)
    row_dicts = [dict(zip(columns, row)) for row in rows]
    return QueryResponse(
        database=str(path),
        sql=sql_statement,
        columns=columns,
        rows=row_dicts,
        row_count=len(row_dicts),
        truncated=truncated,
    )


def _sanitize_sql(sql: str) -> str:
    stripped = sql.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].strip()
    if ";" in stripped:
        raise HTTPException(status_code=400, detail="Only a single SQL statement is allowed.")
    lowered = stripped.lower()
    if lowered.startswith(("select", "with", "pragma", "explain")):
        return stripped
    raise HTTPException(status_code=400, detail="Only read-only SELECT/PRAGMA/EXPLAIN statements are permitted.")


INDEX_HTML = """<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"UTF-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
<title>SQLite Explorer</title>
<style>
:root { font-family: system-ui, sans-serif; color: #111; background: #f5f6fb; }
body { margin: 0; padding: 24px; }
main { max-width: 960px; margin: 0 auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 12px rgba(15, 23, 42, 0.1); padding: 24px; }
h1 { margin-top: 0; }
label { display: block; font-weight: 600; margin-top: 16px; }
input[type=text], textarea { width: 100%; padding: 8px 12px; border: 1px solid #d0d7de; border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace; box-sizing: border-box; }
textarea { min-height: 140px; resize: vertical; }
button { margin-top: 12px; padding: 10px 18px; border-radius: 6px; border: none; background: #2563eb; color: white; font-weight: 600; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
section { margin-top: 24px; }
pre { background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 6px; overflow-x: auto; font-size: 0.875rem; }
table { width: 100%; border-collapse: collapse; margin-top: 12px; }
th, td { border: 1px solid #d0d7de; padding: 8px; text-align: left; font-family: ui-monospace, monospace; font-size: 0.85rem; }
th { background: #f1f5f9; }
#schema-output h3 { margin-bottom: 4px; }
.badge { display: inline-block; padding: 2px 6px; border-radius: 4px; background: #e0f2fe; color: #1e3a8a; font-size: 0.75rem; margin-left: 6px; }
.error { background: #fee2e2; color: #991b1b; padding: 12px; border-radius: 6px; margin-top: 12px; }
</style>
</head>
<body>
<main>
<h1>SQLite Explorer</h1>
<p>Inspect and query databases under <code>__PROJECT_ROOT__</code>.</p>
<label for=\"db-input\">Database path</label>
<input id=\"db-input\" type=\"text\" placeholder=\"data/yc_db.db\">
<div>
<button id=\"load-schema-btn\">Load Schema</button>
</div>
<section>
<h2>Schema</h2>
<div id=\"schema-output\">No schema loaded yet.</div>
</section>
<section>
<h2>Query</h2>
<label for=\"sql-input\">SQL</label>
<textarea id=\"sql-input\" placeholder=\"SELECT name FROM sqlite_master WHERE type='table';\"></textarea>
<label for=\"limit-input\">Result limit</label>
<input id=\"limit-input\" type=\"text\" value=\"200\">
<button id=\"run-query-btn\">Run Query</button>
<div id=\"query-error\"></div>
<div id=\"query-output\"></div>
</section>
</main>
<script>
const dbInput = document.getElementById('db-input');
const loadSchemaBtn = document.getElementById('load-schema-btn');
const schemaOutput = document.getElementById('schema-output');
const sqlInput = document.getElementById('sql-input');
const limitInput = document.getElementById('limit-input');
const runQueryBtn = document.getElementById('run-query-btn');
const queryOutput = document.getElementById('query-output');
const queryError = document.getElementById('query-error');

async function loadSchema() {
    const dbPath = dbInput.value.trim();
    if (!dbPath) {
        alert('Provide a database path first.');
        return;
    }
    schemaOutput.textContent = 'Loading...';
    try {
        const response = await fetch(`/schema?db_path=${encodeURIComponent(dbPath)}`);
        if (!response.ok) {
            throw new Error(await response.text());
        }
        const payload = await response.json();
        renderSchema(payload.tables);
    } catch (error) {
        schemaOutput.innerHTML = `<div class="error">${error.message}</div>`;
    }
}

function renderSchema(tables) {
    if (!tables.length) {
        schemaOutput.textContent = 'No user tables found.';
        return;
    }
    const parts = tables.map(table => {
        const rows = table.columns.map(col => `
            <tr>
                <td>${col.name}</td>
                <td>${col.type}</td>
                <td>${col.notnull ? 'YES' : 'NO'}</td>
                <td>${col.default ?? ''}</td>
                <td>${col.primary_key ? 'YES' : 'NO'}</td>
            </tr>
        `).join('');
        return `
            <div>
                <h3>${table.name}<span class="badge">${table.type}</span></h3>
                <table>
                    <thead><tr><th>Name</th><th>Type</th><th>Not Null</th><th>Default</th><th>PK</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    });
    schemaOutput.innerHTML = parts.join('');
}

async function runQuery() {
    queryOutput.textContent = '';
    queryError.textContent = '';
    const dbPath = dbInput.value.trim();
    if (!dbPath) {
        alert('Provide a database path first.');
        return;
    }
    const sql = sqlInput.value.trim();
    if (!sql) {
        alert('Provide SQL to execute.');
        return;
    }
    const limit = parseInt(limitInput.value, 10) || 200;
    runQueryBtn.disabled = true;
    try {
        const response = await fetch('/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ db_path: dbPath, sql, limit })
        });
        if (!response.ok) {
            const errorPayload = await response.json().catch(() => ({}));
            const message = errorPayload.detail || 'Query failed.';
            queryError.innerHTML = `<div class="error">${message}</div>`;
            return;
        }
        const payload = await response.json();
        renderQuery(payload);
    } catch (error) {
        queryError.innerHTML = `<div class="error">${error.message}</div>`;
    } finally {
        runQueryBtn.disabled = false;
    }
}

function renderQuery(result) {
    if (!result.columns.length) {
        queryOutput.textContent = 'Query executed, but no columns returned.';
        return;
    }
    const header = result.columns.map(col => `<th>${col}</th>`).join('');
    const rows = result.rows.map(row => {
        const cells = result.columns.map(col => `<td>${formatValue(row[col])}</td>`).join('');
        return `<tr>${cells}</tr>`;
    }).join('');
    const info = result.truncated ? `<p>Showing ${result.row_count} rows (truncated).</p>` : `<p>Returned ${result.row_count} rows.</p>`;
    queryOutput.innerHTML = `${info}<table><thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table>`;
}

function formatValue(value) {
    if (value === null || value === undefined) {
        return '';
    }
    if (typeof value === 'object') {
        return JSON.stringify(value);
    }
    return value;
}

loadSchemaBtn.addEventListener('click', loadSchema);
runQueryBtn.addEventListener('click', runQuery);

dbInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
        loadSchema();
    }
});

sqlInput.value = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;";
</script>
</body>
</html>"""
