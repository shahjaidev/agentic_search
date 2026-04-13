# Honcho repo flow notes

## What Honcho is
- Honcho separates functionality into **Storage** and **Insights/Reasoning** services.
- It models both humans and agents as **peers** in a unified entity model.

## Core flow (ingest -> derive -> retrieve)
1. App posts messages to a workspace/session.
2. Message API stores messages, then enqueues payloads for async processing.
3. Deriver queue creates/executes tasks (representation updates, summaries, webhooks, etc.).
4. At read time, callers use context/search/representation/chat endpoints.
5. Search combines semantic + full-text retrieval with Reciprocal Rank Fusion (RRF).

## Search behavior
- Full-text path uses Postgres FTS with `ILIKE` fallback, plus special-character handling.
- Semantic path embeds query text and runs vector similarity (pgvector or external vector store).
- If both are available, results are fused via RRF.

## Key difference vs "just hybrid/vector search"
- **Vector search only**: retrieves nearest chunks/messages by embedding similarity.
- **Hybrid search only**: fuses lexical and semantic retrieval for better recall/precision.
- **Honcho**: includes hybrid retrieval, but adds an async reasoning layer that derives persistent conclusions/representations and offers higher-level interfaces (`context`, `representation`, `chat`) that go beyond retrieval.
