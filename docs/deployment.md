# Deployment

> **AI Context Summary**: Docker Compose is the intended local/demo deployment shape, with API, worker, and Postgres services. A real shared deployment can run the same Compose stack on a small VM. GitHub Pages or static hosting cannot run this app because it needs a backend, database, worker, and Slack webhook endpoint.

## Overview

For demos and trial use, use Docker Compose. For a link that remains available without a laptop, deploy the same app to a small VM or equivalent container host with persistent Postgres storage and HTTPS.

Ngrok is useful for local Slack testing, not durable production deployment.

## Key Concepts

- **Postgres volume** — `postgres_data` persists Docker DB data (`docker-compose.yml:54`).
- **API port** — host port 8000 maps to API container port 8000 (`docker-compose.yml:28`).
- **Worker interval** — Docker worker defaults to 30 seconds (`docker-compose.yml:45`).
- **Backfill limit** — worker defaults to 200 messages per channel (`docker-compose.yml:46`).
- **Healthcheck** — Postgres health gates API/worker startup (`docker-compose.yml:12`).

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

## Persistent VM Shape

A small VM can run:

- Docker and Docker Compose
- the `api`, `worker`, and `db` services
- a reverse proxy with HTTPS
- a real domain or stable public URL for Slack Events
- persistent disk for Postgres data

Keep `.env` on the server and out of git. Back up the Postgres volume before trial data matters.

## Slack Public URL

Slack Event Subscriptions need:

```text
https://your-domain/slack/events
```

For local testing, ngrok can provide that URL:

```bash
ngrok http 8000
```

Do not use ngrok as an always-on lab deployment unless you intentionally accept tunnel availability and account limits.

## Reset And Backfill

Reset archive rows:

```bash
docker compose exec api python scripts/reset_archive.py
```

Backfill after reset because Slack does not replay old Events API deliveries:

```bash
docker compose exec api python scripts/backfill_joined_channels.py --limit 200
```

## Cross-References

- Related: [docs/getting-started.md](./getting-started.md)
- Related: [docs/security.md](./security.md)
- Related: [docs/database.md](./database.md)
