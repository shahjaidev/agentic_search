# Agentic Search Prototype

This repository implements the prototype described in `plan.md`. It includes a FastAPI backend, Streamlit chat UI, background enrichment worker, and SQLite persistence layer.

## Getting Started

1. **Create a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   Required packages:

   - `fastapi`
   - `uvicorn`
   - `sqlalchemy`
   - `pydantic`
   - `streamlit`
   - `requests`

2. **Configure environment**

   Copy `.env.example` to `.env` and update values as needed.

   ```bash
   cp .env.example .env
   ```

3. **Initialise the database**

   Tables are created automatically on first run, but you can pre-create them by invoking the backend once:

   ```bash
   uvicorn backend_api:app --reload
   ```

4. **Run the services**

   - **Backend API:**

     ```bash
     uvicorn backend_api:app --reload
     ```

   - **Streamlit UI:**

     ```bash
     streamlit run streamlit_app.py
     ```

   - **Background Agent:**

     ```bash
     python background_agent.py
     ```

## Development Notes

- The LLM integration is stubbed in `llm.py` to produce deterministic structured JSON that mirrors the expected Gemini output.
- Enrichment jobs add new columns to the `startups` table and populate them with mock values.
- SQL executed by the backend is stored for auditing in the `executed_sql` table.
