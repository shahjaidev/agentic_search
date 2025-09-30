# Polymarket Data Utilities

The Polymarket pipeline mirrors all live markets into `polymarket/data/polymarket_markets.db` via `python polymarket/get_polymarket_markets.py`. As of 2025-09-29 the database exposes:

- `polymarket_markets`: canonical market snapshot (one row per market).
- `polymarket_markets_fts`: FTS5 mirror of the natural-language columns for fast semantic search.

## Text Search (FTS5)

The fetch script now ensures these objects exist and stay in sync:

```sql
CREATE VIRTUAL TABLE polymarket_markets_fts USING fts5(
    market_id UNINDEXED,
    question,
    description,
    market_slug,
    tags,
    market_category,
    market_category_name,
    market_category_l1_name,
    market_category_l2_name,
    market_category_l3_name,
    content='polymarket_markets',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
```

Common Gemini prompts can combine text search with structured filters:

```sql
-- Surface active presidential-election markets ending in 2024
SELECT m.market_id, m.question, m.end_date_iso
FROM polymarket_markets m
JOIN polymarket_markets_fts f ON f.rowid = m.rowid
WHERE f.polymarket_markets_fts MATCH '"presidential election" NEAR/2 2024'
  AND m.market_category_l1_name = 'Politics'
  AND date(m.end_date_iso) <= date('2024-12-31')
ORDER BY m.end_date_iso;
```

```sql
-- Grab markets tagged for the NBA Finals using prefix search
SELECT market_id, question
FROM polymarket_markets
WHERE rowid IN (
    SELECT rowid
    FROM polymarket_markets_fts
    WHERE polymarket_markets_fts MATCH 'nba* finals'
);
```

## Structured Indexes

Helpful single-column indexes are also kept up-to-date:

- `idx_polymarket_markets_end_date_iso`
- `idx_polymarket_markets_game_start_time`
- `idx_polymarket_markets_market_category_name`
- `idx_polymarket_markets_market_category_l1_name`
- `idx_polymarket_markets_market_category_l2_name`
- `idx_polymarket_markets_market_category_l3_name`

These cover common Gemini filters like date range, league, or sub-category selection. Additional indexes can be added by extending `STRUCTURED_INDEX_COLUMNS` in `polymarket/get_polymarket_markets.py`.

## Regenerating The FTS Index

If you import historical snapshots or bulk-edit the base table, force a rebuild:

```bash
sqlite3 polymarket/data/polymarket_markets.db "INSERT INTO polymarket_markets_fts(polymarket_markets_fts) VALUES('rebuild');"
```

## Gemini Prompt Tips

- Prefer `MATCH` queries for fuzzy keyword/phrase lookup, then narrow with SQL predicates (`end_date_iso`, `market_category_*`).
- Use `snippet(polymarket_markets_fts, ...)` in intermediate steps to show Gemini the highlighted context.
- Teach the agent that `rowid` links the base and FTS tables; joins must be on `rowid`, not `market_id`.
