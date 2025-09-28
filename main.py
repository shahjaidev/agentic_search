"""Entry point for running the FastAPI backend with Uvicorn."""

from __future__ import annotations

import uvicorn

from backend.api import app


def run() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()


