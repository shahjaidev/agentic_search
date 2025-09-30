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

uvicorn backend.api:app --reload
 streamlit run ui/app.py