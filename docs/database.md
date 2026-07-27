# Database

> **AI Context Summary**: SQLAlchemy models define canonical papers, citations, Slack channels/users, Slack mentions, one encrypted Slack Installation, one encrypted Trial Zotero Destination, OAuth attempts, Zotero sync state, and related-paper suggestion state. Uniqueness constraints enforce source-level paper dedupe, mention idempotency, and related-suggestion idempotency. There is no Alembic migration layer yet, so schema changes need explicit care.

## Overview

The database stores canonical item metadata separately from Slack mention provenance. One `Paper` can have many `SlackMention` rows. The current schema uses `source_type` plus `source_id` dedupe so arXiv, DOI, Semantic Scholar, and future scholarly sources can share the same canonical-item pattern.

The application creates tables at startup with `Base.metadata.create_all` (`app/database.py:24`). This is practical for the current demo, but persistent production data needs migrations before schema changes.

## Key Concepts

- **Declarative base** — `Base` lives in `app/database.py:9`.
- **Engine config** — SQLite gets `check_same_thread=False`; other engines use default kwargs (`app/database.py:13`).
- **Canonical paper uniqueness** — `source_type` and `source_id` unique together (`app/models.py:25`).
- **Mention uniqueness** — channel, message timestamp, and paper unique together (`app/models.py:88`).
- **Zotero sync keys** — record group-library item, note, and channel collection mappings (`app/models.py:115`).
- **Related-paper state** — records Semantic Scholar generation status and suggestion rows.
- **Single installation** — one Slack workspace credential and activation state.
- **Single Zotero destination** — one verified destination credential for the trial.
- **Ingestion event key** — prevents repeated Slack/backfill work (`app/models.py:140`).

## Core Tables

`papers` stores source identity, title, authors, abstract, categories, canonical/PDF URLs, metadata status, retry state, and timestamps (`app/models.py:23`). `paper_citations` stores preferred BibTeX provider data (`app/models.py:54`).

`slack_mentions` stores channel/user identity, display names when known, message/thread timestamps, original URL, permalink, and posted timestamp (`app/models.py:86`). It does not store full Slack message text.

`channels` and `users` cache Slack names for filtering and display (`app/models.py:66`, `app/models.py:77`).

`zotero_collection_syncs` maps Slack channel IDs to Zotero collection keys. `zotero_item_syncs` maps local papers to Zotero item and bot-note keys, records sync status/errors, and stores retry timing.

`related_paper_runs` stores one Semantic Scholar recommendation state row per source paper. `related_paper_suggestions` stores ranked external suggestions, display metadata, stable identifiers, and uniqueness by source paper/provider/suggested paper.

`slack_installations` stores the one workspace identity, bot identity, granted
scopes, active state, and encrypted bot credential. `slack_oauth_attempts` stores
hashed, expiring, one-time authorization state and credential-free outcomes.
`trial_zotero_destinations` stores the single group ID, verification state, and
encrypted Zotero credential. Plaintext Slack and Zotero credentials do not
belong in database rows.

The verified `trial_zotero_destinations` row is the sole production Zotero
credential source. Operators configure it through authenticated `/status`;
deployment environment variables do not supply a group ID or API key.

## Idempotency Rules

`ingest_slack_message` exits early when an `event_key` already exists (`app/services/ingestion.py:48`). For each URL, it looks up the canonical paper by source identity before creating a new one (`app/services/ingestion.py:61`). Before inserting a mention, it checks for an existing channel/message/paper row (`app/services/ingestion.py:86`).

New sync features should mirror that style. A retry must update or no-op; it must not create duplicate Zotero items, collections, notes, tags, or related-paper records.

## Schema Change Guidance

Before adding persistent production data, add a migration plan. Until migrations exist, schema changes are acceptable for local/demo data but should be called out clearly.

F-13 deliberately uses one destructive local schema recreation before its first
OAuth test:

```bash
docker compose down -v
docker compose up --build
```

No Alembic migration is implied. After that one-time step, ordinary
`scripts/reset_archive.py` resets preserve installation and destination rows.
The explicit `scripts/reset_credentials.py` flow removes only those credentials
and requires reauthorization; it should not be replaced with routine volume
deletion.

Zotero item keys, collection mappings, Bot-Owned Note keys, and sync status are now persisted. External related suggestions are stored separately from factual metadata and Slack mentions. Future bot-owned tag decisions should follow the same pattern rather than mixing generated curation into Slack mention rows.

## Query Patterns

Search builds mention statistics as a grouped subquery and joins papers to that subquery (`app/services/search.py:48`). This means filters on channel, user, and date apply through mentions rather than paper metadata.

Metadata refresh selects pending or retryable failed papers ordered by creation time (`app/services/metadata.py:17`). Keep this queue-like behavior in mind when adding sync jobs: failed external work should be retryable without hiding the underlying item.

## Zotero State

Store bot-owned external identifiers explicitly. A local paper should know which Zotero item it created, which channel collections it belongs to, and which Bot-Owned Note should be updated. Human Zotero edits should not be inferred from local state unless a refresh operation explicitly checks Zotero.

## Testing Database Behavior

Use the in-memory SQLite fixture for service-level tests, but remember that Postgres full-text search behaves differently from SQLite fallback search. For persistence-sensitive behavior, assert domain outcomes rather than dialect-specific SQL.

When adding constraints, test both the happy path and duplicate/retry path. Integrity errors should roll back cleanly and leave the caller with a safe no-op or recorded failure.

Prefer small fixtures that create the minimum rows needed for the behavior under test.

## Cross-References

- Related: [docs/architecture.md](./architecture.md)
- Related: [docs/testing.md](./testing.md)
- Related: [docs/backend.md](./backend.md)
