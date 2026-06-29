# Architecture

> **AI Context Summary**: Slack Paper Archive is a FastAPI app with server-rendered pages, Slack Events ingestion, background metadata/catch-up work, and SQLAlchemy persistence. The architecture separates request routing, link ingestion, external API integration, source extraction, and search. The current target is a Zotero-first trial, so preserve idempotent ingestion and human-safe sync boundaries.

## Overview

The app has three runtime services in Docker Compose: `api`, `worker`, and `db`. The `api` service serves FastAPI routes and templates, receives Slack Events at `/slack/events`, and stores normalized records. The `worker` service refreshes metadata and performs Slack catch-up for known channels. The `db` service is Postgres for Docker deployments.

Local direct development uses the same FastAPI application but defaults to SQLite through `Settings.database_url` (`app/config.py:10`). This is useful for quick tests and `uvicorn`, while Docker matches the intended deployment shape.

The current domain model is still named around `Paper`, but the Zotero trial spec is broader: canonical scholarly items, Slack mentions, channel collections, Bot-Owned Notes, external related-paper suggestions, and later rule-based tags. Keep new implementation compatible with that direction rather than hardening arXiv-only assumptions.

## Key Concepts

- **App entrypoint** — FastAPI app, templates, static mount, startup DB initialization (`app/main.py:26`).
- **Authenticated local surface** — shared-password login gates search, details, status, and BibTeX (`app/main.py:41`).
- **Slack Events endpoint** — verifies Slack signatures, handles URL verification, enriches message data, and ingests links (`app/main.py:193`).
- **Canonical paper record** — `Paper` is unique by `source_type` + `source_id` (`app/models.py:23`).
- **Slack mention record** — each share is unique by channel, message timestamp, and paper (`app/models.py:86`).
- **Source extractor** — URL normalization and metadata fetch live behind extractor modules (`app/extractors/arxiv.py:15`).
- **Worker loop** — periodic metadata refresh and channel catch-up (`app/worker.py:10`).

## Runtime Data Flow

```text
Slack message
  -> /slack/events
  -> verify_slack_signature
  -> slack_message_from_event
  -> enrich_slack_message
  -> ingest_slack_message
  -> Paper + SlackMention + IngestionEvent
  -> worker refreshes metadata/citations
  -> local UI and future Zotero sync read canonical records
```

Slack Events are intentionally silent. The app does not reply in Slack, post digests, or act like a chatbot. The first trial monitors only opted-in public channels.

## Request Layer

`app/main.py` owns the web routes. `/` renders the search page, `/search/results` returns partial search HTML for live search, `/papers/{paper_id}` renders details, `/papers/{paper_id}.bib` returns BibTeX, `/status` renders a small operator status page, and `/slack/events` receives Slack callbacks.

Routes should stay thin. Put parsing, sync, Slack, Zotero, source metadata, and retry behavior into service modules instead of expanding route bodies.

## Service Layer

`app/services/ingestion.py` extracts URLs, chooses an extractor, creates or updates canonical paper records, records mentions, and writes `IngestionEvent` keys. `ingest_slack_message` checks `event_key` before work (`app/services/ingestion.py:48`) and uses mention uniqueness to avoid duplicate shares (`app/services/ingestion.py:86`).

`app/services/slack.py` owns Slack trust boundaries. Signature verification uses Slack's timestamp and HMAC scheme (`app/services/slack.py:17`). Web API calls are wrapped by `SlackApiClient.api`, which raises on Slack `ok: false` responses (`app/services/slack.py:78`).

`app/services/metadata.py` processes pending/failed papers with retry backoff. Failed fetches store errors and schedule retries rather than deleting records (`app/services/metadata.py:54`).

## Persistence Boundary

The current database is created by `Base.metadata.create_all` (`app/database.py:24`). This is fine for the demo/trial shape, but production-like persistent data needs migrations before schema-changing work.

Database models use SQLAlchemy ORM. Keep uniqueness and idempotency at both the service level and the database level where possible.

## Planned Zotero Direction

The first implementation pass should prove Slack-to-Zotero sync: a synced item, lazy channel collection creation, and a `Bot notes` note containing Slack provenance. External related papers come after plain sync and should appear in `Bot notes` as suggestions. Rule-based `auto:` tags come after external related papers.

Do not auto-import external related papers. Manual import can come later, and accepted suggestions should inherit the source paper's channel collection.

## Extension Points

Add new link sources under `app/extractors/` and keep their normalization pure. Add new external integrations under `app/services/` so request handlers and workers can share behavior.

For Zotero, prefer a dedicated service boundary that translates canonical local state into bot-owned Zotero items, collections, notes, and tags. Do not let templates or routes construct Zotero payloads directly.

For external related papers, store enough local state to avoid repeatedly asking the same recommendation source for the same paper on every page view or worker pass.

## Cross-References

- Related: [docs/backend.md](./backend.md)
- Related: [docs/database.md](./database.md)
- Related: [docs/api.md](./api.md)
- Related: [docs/deployment.md](./deployment.md)
- Related: [docs/workflow.md](./workflow.md)
