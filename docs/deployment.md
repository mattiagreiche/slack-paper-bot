# Deployment

> **AI Context Summary**: The checked-in Docker Compose file is the local/demo shape, with API, worker, and Postgres services. It is not a production VM configuration. GitHub Pages or static hosting cannot run this app because it needs a backend, database, worker, and Slack webhook endpoint.

## Overview

For local demos and trial development, use Docker Compose. For a link that
remains available without a laptop, create a production deployment profile for
a small VM or equivalent container host with persistent Postgres storage,
HTTPS, restricted network exposure, backups, and non-development secrets.

Ngrok is useful for local Slack testing, not durable production deployment.

## Key Concepts

- **Postgres volume** — `postgres_data` persists Docker DB data (`docker-compose.yml:54`).
- **API port** — host port 8000 maps to API container port 8000 (`docker-compose.yml:28`).
- **Worker interval** — Docker worker defaults to 60 seconds unless `.env` overrides it.
- **Backfill limit** — worker defaults to 200 messages per channel (`docker-compose.yml:46`).
- **Healthcheck** — Postgres health gates API/worker startup (`docker-compose.yml:12`).
- **OAuth callback** — `/slack/oauth/callback` completes workspace authorization.
- **Events webhook** — `/slack/events` receives signed Slack event deliveries.

## Local Docker

```bash
cp .env.example .env
docker compose up --build
```

Restart after changing Slack scopes or env vars:

```bash
docker compose down
docker compose up --build
```

The API receives Slack signing/OAuth secrets and the credential-encryption key.
The worker receives the encryption key, but not the OAuth client secret,
redirect URI, or signing secret. Compose mounts only `app/` and `scripts/` into
the containers, so the worker cannot load the repository `.env` file through
the development source mount. During migration only, both services may receive
`SLACK_OAUTH_MIGRATION_MODE`, `SLACK_LEGACY_TEAM_ID`, and `SLACK_BOT_TOKEN`.

Zotero group credentials are not deployment environment variables. An
authenticated operator verifies and saves the Trial Zotero Destination through
`/status`; API and worker operations then use that encrypted persisted record.
`ZOTERO_API_BASE_URL` is retained only on the API as an optional verification
default.

## Persistent VM Requirements

Do not expose the checked-in development Compose stack directly on a VM. Before
a persistent trial, provide a production override or deployment definition that:

- removes Uvicorn `--reload` and development bind mounts
- requires strong application, database, and shared-password secrets
- exposes only the HTTPS reverse proxy publicly and keeps Postgres private
- adds API and worker restart policies and health monitoring
- stores Postgres data on persistent disk
- backs up both Postgres and `CREDENTIAL_ENCRYPTION_KEY` off-host and tests restoration
- uses a real domain or stable HTTPS URL for Slack OAuth and Events

Keep `.env` mode `0600` on the server and out of git. Schema migrations and a
tested backup/restore procedure are required before persistent data matters.

## Slack Public URLs

Slack needs two distinct HTTPS URLs:

```text
OAuth redirect:      https://your-domain/slack/oauth/callback
Event subscription: https://your-domain/slack/events
```

For local testing, ngrok can provide that URL:

```bash
ngrok http 8000
```

If ngrok assigns a new hostname, update the OAuth redirect in Slack, the Event
Subscriptions request URL, and `SLACK_OAUTH_REDIRECT_URI` in `.env`. Restart the
API before starting another authorization attempt. The callback exchanges the
short-lived OAuth code; the events endpoint verifies Slack request signatures.

Do not use ngrok as an always-on lab deployment unless you intentionally accept tunnel availability and account limits.

## Schema Recreation, Reset, And Backfill

There is deliberately no invented Alembic migration for F-13. Before the first
OAuth test, recreate the local Postgres schema once:

```bash
docker compose down -v
docker compose up --build
```

This is destructive and removes all local archive and credential data. It is a
one-time pre-OAuth development step, not the ordinary reset procedure.

Reset archive rows:

```bash
docker compose exec api python scripts/reset_archive.py
```

The ordinary reset preserves the Slack Installation, its active/inactive state,
and the Trial Zotero Destination. To remove stored credentials while preserving
archive history, use the separate credential reset with its exact confirmation:

```bash
docker compose exec api python scripts/reset_credentials.py --confirm FULL-CREDENTIAL-RESET
```

Afterward, Slack must be authorized and the Zotero destination configured again.

Backfill after reset because Slack does not replay old Events API deliveries:

```bash
docker compose exec api python scripts/backfill_joined_channels.py --limit 200
```

## OAuth Migration And Mila Replacement

The manually configured bot token is an explicitly temporary bridge:

```text
SLACK_OAUTH_MIGRATION_MODE=true
SLACK_LEGACY_TEAM_ID=<test workspace team ID>
SLACK_BOT_TOKEN=<temporary xoxb token>
```

Authorize the same test workspace through `/slack/install`, configure and
verify the Trial Zotero Destination through authenticated `/status`, activate
the installation, then verify:

1. A signed `message.channels` event reaches `/slack/events` and is ingested.
2. Worker catch-up or operator backfill reads the same workspace successfully.
3. Zotero sync still targets the one configured Trial Zotero Destination.

Only after all three checks pass, remove the token, team ID, and migration-mode
setting from `.env`, restart, and repeat the event plus worker checks with OAuth
credentials alone. That is the deletion gate for removing the legacy variables
and compatibility path from deployment/application configuration.

To move the trial to Mila, use the authenticated operator-approved replacement
flow rather than authorizing a second concurrent workspace. Mila must complete
OAuth and becomes the single inactive installation; verify the Zotero
destination and activate it. The old workspace credential is no longer used,
while its archive records remain historical and are never treated as Mila data.

## Cross-References

- Related: [docs/getting-started.md](./getting-started.md)
- Related: [docs/security.md](./security.md)
- Related: [docs/database.md](./database.md)
