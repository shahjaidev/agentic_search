"""Background worker that processes enrichment jobs."""
from __future__ import annotations

import logging
import time

from database import (
    ensure_startup_attribute,
    fetch_pending_jobs,
    get_startup_ids,
    mark_job_complete,
    mark_job_failed,
    update_startup_attribute,
)
from settings import get_settings


LOGGER = logging.getLogger("background_agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def enrich_attribute(attribute_name: str) -> None:
    """Mock enrichment that writes synthetic values."""

    ensure_startup_attribute(attribute_name)
    for startup_id in get_startup_ids():
        value = f"Enriched {attribute_name} value for startup {startup_id}"
        update_startup_attribute(startup_id, attribute_name, value)


def process_jobs_once() -> int:
    """Fetch and process pending jobs once. Returns count of processed jobs."""

    processed = 0
    jobs = fetch_pending_jobs()
    for job in jobs:
        try:
            LOGGER.info("Processing enrichment job %s", job.id)
            enrich_attribute(job.attribute_name)
            mark_job_complete(job.id)
            processed += 1
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.exception("Failed to process job %s", job.id)
            mark_job_failed(job.id, str(exc))
    return processed


def run_forever() -> None:
    """Continuously process jobs with a configurable interval."""

    settings = get_settings()
    while True:
        processed = process_jobs_once()
        if processed == 0:
            LOGGER.debug("No jobs to process. Sleeping...")
        time.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    run_forever()
