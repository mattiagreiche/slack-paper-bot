# Getting Started

> **AI Context Summary**: Use Docker Compose for the realistic app shape: FastAPI API, Postgres, and worker. Direct local development uses SQLite and is useful for route/service work. Slack testing requires a public tunnel, Slack OAuth app credentials, request signing, and a stable credential-encryption key. Zotero sync requires group-library write credentials.

## Overview

Start with Docker when testing Slack ingestion, worker catch-up, or Postgres behavior. Use direct `uvicorn` when iterating on routes, templates, or isolated service changes that do not require the worker.

The app gates local web pages with a shared password. Slack Events use Slack request signing, not the shared web password. During the Zotero trial, the bot monitors only public channels it has joined.

## Key Concepts

- **Settings source** — `Settings` loads `.env` and ignores extra values (`app/config.py:7`).
- **Docker API service** — runs `uvicorn app.main:app` on port 8000 (`docker-compose.yml:18`).
- **Docker worker service** — runs `python -m app.worker` with the same DB (`docker-compose.yml:36`).
- **Local SQLite default** — direct runs use `sqlite:///./paper_archive.db` (`app/config.py:10`).

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open `http://localhost:8000` and log in with `SHARED_PASSWORD`. If `.env` is absent, the default password is `papers`.

## Docker Setup

```bash
cp .env.example .env
docker compose up --build
```

Docker starts Postgres, the API, and the worker. The API is available on `http://localhost:8000`.

Reset archive data without deleting the Postgres volume:

```bash
docker compose exec api python scripts/reset_archive.py
```

Because there is no Alembic migration layer, perform one deliberate schema
recreation before the first F-13 OAuth test:

```bash
docker compose down -v
docker compose up --build
```

This deletes all local Postgres data and is not the normal reset command.
Ordinary `reset_archive.py` runs preserve the Slack Installation, its activation
state, and the Trial Zotero Destination.

## Slack Setup

Slack local testing needs a public HTTPS URL. Run the app in one terminal:

```bash
docker compose up --build
```

Run a tunnel in another:

```bash
ngrok http 8000
```

Configure Slack Event Subscriptions with:

```text
https://your-ngrok-url/slack/events
```

Configure the distinct OAuth redirect URL with:

```text
https://your-ngrok-url/slack/oauth/callback
```

Subscribe to `message.channels` and add `channels:history`, `channels:read`, and
`users:read`. Put `SLACK_SIGNING_SECRET`, `SLACK_CLIENT_ID`,
`SLACK_CLIENT_SECRET`, `SLACK_OAUTH_REDIRECT_URI`, and one stable
`CREDENTIAL_ENCRYPTION_KEY` in `.env`, restart Docker, then open
`/slack/install`. The callback completes installation; `/slack/events` handles
signed event deliveries.

When an ngrok hostname changes, update both URLs in Slack and update
`SLACK_OAUTH_REDIRECT_URI` in `.env`. Restart the API before beginning a new
authorization attempt.

The legacy `SLACK_BOT_TOKEN` path is a temporary migration bridge only. If it is
needed before OAuth smoke verification, set it together with
`SLACK_OAUTH_MIGRATION_MODE=true` and the exact `SLACK_LEGACY_TEAM_ID`. Remove
all three after the OAuth-installed test workspace passes an event-ingestion
smoke test and a worker catch-up/backfill smoke test, then restart with migration
mode off and repeat those checks.

## Zotero Setup

Create a Zotero group library and a Zotero API key with write access to that
group. Log in, open `/status`, enter the numeric group ID and API key under
**Trial destination**, and select **Verify and save**.

The app encrypts and persists the verified Trial Zotero Destination. It is the
only production credential source; do not add the group ID or API key to
`.env`. `ZOTERO_API_BASE_URL` is optional and only changes the API endpoint
default used during verification. When metadata is ready, the worker reads the
persisted destination, syncs each public-channel paper into the group library,
creates a collection for the Slack channel if needed, and writes Slack
provenance into a child note titled `Bot notes`.

Optional related-paper suggestions use Semantic Scholar Recommendations API and are off by default:

```bash
RELATED_PAPERS_ENABLED=true
RELATED_PAPERS_LIMIT=5
SEMANTIC_SCHOLAR_API_KEY=...  # optional
```

When enabled, the worker stores up to five external suggestions per synced item and refreshes Zotero `Bot notes`. Suggestions are marked bot-generated and are not automatically imported as Zotero items.

## Backfill

Slack will not replay old Events API deliveries after a database reset. Run joined-channel backfill once after a reset:

```bash
docker compose exec api python scripts/backfill_joined_channels.py --limit 200
```

Use date bounds when needed:

```bash
docker compose exec api python scripts/backfill_joined_channels.py --since 2026-05-01 --until 2026-05-22 --limit 1000
```

`--limit` counts Slack messages per channel, not papers.

## Reset And Workspace Replacement

Use `scripts/reset_archive.py` for ordinary paper/mention/channel/sync resets.
It preserves stored Slack authorization and the verified Trial Zotero
Destination.

For an intentional credential-only reset, supply the exact destructive
confirmation literal:

```bash
docker compose exec api python scripts/reset_credentials.py --confirm FULL-CREDENTIAL-RESET
```

This removes the Slack Installation and Trial Zotero Destination while
preserving archive records; Slack must be authorized and Zotero configured
again. Do not substitute `docker compose down -v`, which also destroys archive
history.

To replace the test workspace with Mila, use the authenticated operator
replacement action, complete Mila's OAuth authorization, verify the same Trial
Zotero Destination, and activate Mila. Replacement is explicit: Mila becomes
the single inactive installation, the former credential stops being used, and
prior test-workspace records remain historical rather than becoming Mila data.

## Common Failure Modes

If `/login` rejects the password after Docker restart, check `.env` and `SHARED_PASSWORD`. If Slack user names remain as IDs, confirm `users:read` was granted and the app was reinstalled. If catch-up logs `missing_scope`, add `channels:read`, reinstall the Slack app, and restart Docker. If Zotero sync stays at zero, open authenticated `/status` and confirm the Trial Zotero Destination is present and verified, the API key can write to that group, and the Slack Installation is active. If related papers stay pending or failed, confirm `RELATED_PAPERS_ENABLED=true`, check `/status`, and consider setting `SEMANTIC_SCHOLAR_API_KEY` for rate limits.

## Cross-References

- Related: [docs/deployment.md](./deployment.md)
- Related: [docs/testing.md](./testing.md)
- Related: [docs/authentication.md](./authentication.md)
