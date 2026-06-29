# Database

> **AI Context Summary**: SQLAlchemy models define canonical papers, citations, Slack channels/users, Slack mentions, ingestion events, and Zotero sync state. Uniqueness constraints enforce source-level paper dedupe and mention idempotency. There is no Alembic migration layer yet, so schema changes need explicit care.

## Overview

The database stores canonical item metadata separately from Slack mention provenance. One `Paper` can have many `SlackMention` rows. The current schema uses `source_type` plus `source_id` dedupe so arXiv, DOI, Semantic Scholar, and future scholarly sources can share the same canonical-item pattern.

The application creates tables at startup with `Base.metadata.create_all` (`app/database.py:24`). This is practical for the current demo, but persistent production data needs migrations before schema changes.

## Key Concepts

- **Declarative base** — `Base` lives in `app/database.py:9`.
- **Engine config** — SQLite gets `check_same_thread=False`; other engines use default kwargs (`app/database.py:13`).
- **Canonical paper uniqueness** — `source_type` and `source_id` unique together (`app/models.py:25`).
- **Mention uniqueness** — channel, message timestamp, and paper unique together (`app/models.py:88`).
- **Zotero sync keys** — record group-library item, note, and channel collection mappings (`app/models.py:115`).
- **Ingestion event key** — prevents repeated Slack/backfill work (`app/models.py:140`).

## Core Tables

`papers` stores source identity, title, authors, abstract, categories, canonical/PDF URLs, metadata status, retry state, and timestamps (`app/models.py:23`). `paper_citations` stores preferred BibTeX provider data (`app/models.py:54`).

`slack_mentions` stores channel/user identity, display names when known, message/thread timestamps, original URL, permalink, and posted timestamp (`app/models.py:86`). It does not store full Slack message text.

`channels` and `users` cache Slack names for filtering and display (`app/models.py:66`, `app/models.py:77`).

`zotero_collection_syncs` maps Slack channel IDs to Zotero collection keys. `zotero_item_syncs` maps local papers to Zotero item and bot-note keys, records sync status/errors, and stores retry timing.

## Idempotency Rules

`ingest_slack_message` exits early when an `event_key` already exists (`app/services/ingestion.py:48`). For each URL, it looks up the canonical paper by source identity before creating a new one (`app/services/ingestion.py:61`). Before inserting a mention, it checks for an existing channel/message/paper row (`app/services/ingestion.py:86`).

New sync features should mirror that style. A retry must update or no-op; it must not create duplicate Zotero items, collections, notes, tags, or related-paper records.

## Schema Change Guidance

Before adding persistent production data, add a migration plan. Until migrations exist, schema changes are acceptable for local/demo data but should be called out clearly.

Zotero item keys, collection mappings, Bot-Owned Note keys, and sync status are now persisted. Future generated curation should add separate tables for external related suggestions and bot-owned tag decisions rather than mixing that state into Slack mention rows.

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
