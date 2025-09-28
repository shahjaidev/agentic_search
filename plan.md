# Project Plan

## Goals
- Serve a local chat experience that answers user queries with Gemini 2.5 Flash + Google Grounding.
- Keep SQLlite enriched with columns that capture new user-requested attributes.
- Ensure Gemini prompts return structured JSON that the services can parse reliably.
- Trigger background enrichment after each chat turn without blocking the UI.

## System Pieces
- **Backend API**: FastAPI (or Flask) service invoking Gemini 2.5 Flash with Google Grounding, translating search intents into SQL, querying sqllite, and returning structured JSON responses.
- **Streamlit UI**: Local chat front-end that hits the API, shows history, and schedules background enrichment after each user input.
- **Background Agent (`background_agent.py`)**: Independent worker that reads queued jobs, alters tables to add missing columns, and populates new fields using Gemini's structured JSON output.
- **SQLlite DB**: Stores startup records, enrichment metadata, chat history, job queue/status, and tracks which enrichment columns already exist.

## Build Steps
1. **Environment & Secrets**
   - Create virtualenv, install `streamlit`, `fastapi`/`uvicorn`, `google-generativeai`, `google-cloud-aiplatform`, `psycopg[binary]`, `sqlalchemy`, `alembic`.
   - Load Gemini credentials (2.5 Flash with Grounding config) and DB settings via `.env` and `pydantic` settings.
2. **Database Layer**
   - Define startup base table plus chat history and enrichment jobs tables.
   - Provide helpers to inspect and alter table schema (`ALTER TABLE ADD COLUMN`) when new attributes arrive.
   - Persist executed SQL + results for audit and to prevent duplicate column creation.
3. **Backend API**
   - Expose `/chat` endpoint: accept user message, call Gemini 2.5 Flash with Grounding for structured JSON containing reply, SQL, and enrichment hints.
   - Detect requested attribute (e.g., "founder background"), include it in enrichment job payload, and enqueue job after responding.
   - Add simple health check and structured logging; validate JSON schema before responding.
4. **Streamlit UI**
   - Render chat conversation with session state; submit messages through backend.
   - Display streamed/loading state; surface SQL snippets or result summaries when helpful.
   - Fire-and-forget request to register enrichment job (reuse `/chat` response metadata).
5. **Background Agent**
   - Poll enrichment job table; for each job determine target attribute, add column to startup table if missing, and populate values for all rows via Gemini's structured JSON output or cached data.
   - Mark job complete once the column is filled, store timestamp, and ensure retries/backoff for failures.


## Handoff Checklist
- `.env.example` with required secrets.
- Instructions for initializing DB schema (`alembic upgrade head`) and handling column additions safely.
- Commands to launch Streamlit, backend API, and background agent.
- Notes on monitoring job table/logs plus verifying new columns appear and are populated.
