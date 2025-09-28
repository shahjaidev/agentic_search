# yc_enrich_multi_attr

`yc_enrich_multi_attr.py` enriches multiple YC company attributes in a single Gemini model call per row. It keeps the SQLite source table up to date while logging every response to a JSONL audit file.

## Prerequisites
- Python 3.10+
- `google-generativeai` (and any other deps listed in `requirements.txt`)
- Environment variable `GOOGLE_API_KEY` (preferred) or `GEMINI_API_KEY`
- Writable access to the target SQLite database (default: `data/yc_companies.db`)

## Key Flags
- `--attribute` / `--query`: Provide matching lists (or one query to reuse) for every attribute you want to enrich.
- `--sources-column`, `--notes-column`, `--raw-column`: Optional mirrors for storing provenance, notes, or raw JSON per attribute.
- `--where`: Restrict which rows are processed.
- `--max-workers`: Control parallel Gemini calls.
- `--jsonl-out`: Path for append-only audit logs (use `-` to disable).
- `--no-force`: Skip already populated rows. Default behaviour re-enriches everything that matches the `WHERE` clause.

## Usage Example
```bash
python yc_enrich_multi_attr.py \
    --db data/yc_companies.db \
    --attribute product_vertical \
    --attribute open_roles \
    --attribute latest_fundraising_amount \
    --attribute latest_fundraising_date \
    --attribute investors \
    --query "Classify this company’s product vertical (e.g., robotics, video generation, social media, fintech, healthtech). Return one clear label." \
    --query "List the active job openings, using the startup’s careers page or recent public postings (e.g., Hacker News 'Who’s Hiring?'). Return a comma-separated string; use an empty string if nothing is verifiable." \
    --query "Report the most recent fundraising amount (USD, integer). If unknown, return an empty string." \
    --query "Provide the date of the most recent fundraising event in ISO format (YYYY-MM-DD). If unknown, return an empty string." \
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
    --where "batch IS NOT NULL AND CAST(substr(batch, -4) AS INTEGER) >= 2025 AND team_size >= 4" \
    --max-workers 32
```

For long-running jobs, monitor stdout for progress totals and check `data/yc_enriched_jsonl.jsonl` for detailed per-row payloads and failures.
