# API And Routes

> **AI Context Summary**: The API surface is small: server-rendered search/detail/status pages, Slack OAuth installation, BibTeX text output, health check, and Slack Events ingestion. OAuth callbacks validate one-time state; Slack Events validate request signatures; local archive pages use shared-password cookie auth. Zotero writes happen from the worker/service layer, not public routes.

## Overview

The app is not a broad public JSON API. Most user-facing behavior is server-rendered HTML. `/search/results` is a small JSON endpoint for live search results. `/slack/oauth/callback` and `/slack/events` are separate public Slack endpoints with different validation rules.

## Key Concepts

- **Health check** — `/healthz` returns `{"ok": True}` (`app/main.py:36`).
- **Login/logout** — shared-password cookie auth (`app/main.py:41`, `app/main.py:62`).
- **Search page** — `/` renders full search page (`app/main.py:69`).
- **Live results** — `/search/results` returns rendered result HTML and count (`app/main.py:99`).
- **Paper detail** — `/papers/{paper_id}` (`app/main.py:140`).
- **BibTeX** — `/papers/{paper_id}.bib` returns text (`app/main.py:126`).
- **Status** — `/status` shows counts, work queues, retry actions, channels, and recent ingestion events (`app/main.py:168`).
- **Operator retry** — `/operator/papers/{paper_id}/retry-metadata`, `/operator/papers/{paper_id}/retry-zotero`, and `/operator/papers/{paper_id}/retry-related` reset failed/pending work for worker pickup.
- **Slack installation** — `/slack/install` begins authorization and `/slack/oauth/callback` completes it.
- **Slack webhook** — `/slack/events` verifies Slack signature and ingests messages (`app/main.py:193`).

## Authentication Boundaries

Local pages use `is_authenticated`, which checks a signed cookie derived from `APP_SECRET_KEY` and `SHARED_PASSWORD` (`app/auth.py:10`). Slack event requests do not use this cookie; they require Slack signature verification (`app/services/slack.py:17`). OAuth callbacks instead require valid, unexpired, one-time state before any authorization-code exchange.

Never expose secrets in route responses. Error messages shown to users should describe the operation, not token values or raw request signatures.

## Slack OAuth Behavior

`GET /slack/install` starts authorization for only
`channels:history`, `channels:read`, and `users:read`.
`GET /slack/oauth/callback` handles Slack approval, denial, and exchange
failures. A successful callback records or idempotently updates the single
installation but leaves it inactive until the Trial Zotero Destination is
verified and an authenticated operator activates it.

An unexpected second workspace is rejected unless an authenticated operator
started the explicit replacement flow. Replacement installs the new workspace
inactive and preserves old archive records as history. Callback responses and
operator status must never display client secrets, bot credentials,
authorization codes, or raw provider payloads.

Authenticated `/status` posts the Trial Zotero Destination to
`POST /operator/zotero-destination`. That route verifies, encrypts, and persists
the group ID and API key. The persisted destination is the sole production
credential source; routes and workers do not fall back to Zotero credential
environment variables.

## Slack Events Behavior

The Slack endpoint handles URL verification (`app/main.py:207`) and ignores non-event callbacks. Message events are converted by `slack_message_from_event`, optionally enriched through Slack Web API, then ingested (`app/main.py:213`).

`POST /slack/events` is not an OAuth redirect. It validates the Slack request
signature, resolves the exact active workspace installation, and does no
ingestion for unknown, inactive, or replaced workspaces. It never falls back to
another workspace credential.

Supported message filtering lives in `slack_message_from_event`: only message events from public channels are accepted during the trial, bot/deleted messages are ignored, private channels are ignored, and empty text is skipped (`app/services/slack.py:41`).

## Search Behavior

Search filters are query string parameters: `q`, `channel`, `user`, `date_from`, `date_to`, and `sort`. Blank date strings are normalized to all-time by `_parse_optional_date` (`app/main.py:256`).

Postgres uses full-text search; SQLite falls back to `ILIKE` patterns (`app/services/search.py:63`). Sort is either recent or mention count.

## Zotero Operator Routes

Operator retry routes are small authenticated POST routes. They do not call external APIs directly; they reset local retry state so the worker can try metadata or Zotero sync again. Keep future destructive or irreversible actions explicit. Do not make Slack postbacks or public routes for Zotero writes during the trial.

## Response Shape Guidance

Server-rendered routes should return HTML templates and redirect unauthenticated users to `/login`. JSON endpoints used by JavaScript should return structured JSON and use HTTP errors for unauthenticated access, matching `/search/results` (`app/main.py:99`).

Text endpoints, such as BibTeX, should stay narrow and authenticated. If future export formats are added, keep them as explicit routes rather than adding mode switches to existing pages.

## Operator Actions

For retry and sync actions, prefer POST routes. A GET route should inspect state, not mutate Zotero or Slack-facing data. Mutating routes should report enough status for the operator to tell whether work was queued, completed, or failed. Error strings rendered in operator pages must be redacted before display.

Manual import of external related papers should be explicit. Do not create a Zotero item because a viewer opened a detail page or because related-paper suggestions were refreshed.

## Testing Routes

Route tests should cover authentication, expected status codes, rendered content markers, and mutation side effects. For Slack webhooks, test URL verification, ignored event types, valid message ingestion, and invalid signature rejection separately.

## Cross-References

- Related: [docs/authentication.md](./authentication.md)
- Related: [docs/backend.md](./backend.md)
- Related: [docs/testing.md](./testing.md)
