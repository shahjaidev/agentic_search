# SQLite Explorer

Simple FastAPI + vanilla JS app to inspect SQLite databases under this project.

## Run Locally

1. Activate your virtualenv and install deps if needed:

   ```bash
   pip install -r requirements.txt
   ```

2. Start the server:

   ```bash
   SQLITE_EXPLORER_ALLOW_ANY=1 uvicorn sqlite_explorer_api:app --reload --port 8002
   ```

3. Open http://127.0.0.1:8002/ in a browser, enter a DB path like `data/yc_db.db`, load the schema, and run read-only queries.
