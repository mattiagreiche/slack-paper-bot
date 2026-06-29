# Getting Started

> **AI Context Summary**: Use Docker Compose for the realistic app shape: FastAPI API, Postgres, and worker. Direct local development uses SQLite and is useful for route/service work. Slack testing requires a public tunnel and valid Slack signing/token configuration. Zotero sync requires group-library write credentials.

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

Delete the whole Postgres volume:

```bash
docker compose down -v
```

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

Subscribe to `message.channels`. Add bot scopes from the README, install or reinstall the Slack app, copy `SLACK_SIGNING_SECRET` and `SLACK_BOT_TOKEN` into `.env`, and restart Docker.

## Zotero Setup

Create a Zotero group library and a Zotero API key with write access to that group. Add these values to `.env`:

```bash
ZOTERO_API_KEY=...
ZOTERO_GROUP_ID=...
```

Restart Docker after changing `.env`. When metadata is ready, the worker syncs each public-channel paper into the group library, creates a collection for the Slack channel if needed, and writes Slack provenance into a child note titled `Bot notes`.

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

## Common Failure Modes

If `/login` rejects the password after Docker restart, check `.env` and `SHARED_PASSWORD`. If Slack user names remain as IDs, confirm `users:read` was granted and the app was reinstalled. If catch-up logs `missing_scope`, add `channels:read`, reinstall the Slack app, and restart Docker. If Zotero sync stays at zero, confirm `ZOTERO_API_KEY` and `ZOTERO_GROUP_ID` are set for a group library the key can write to.

## Cross-References

- Related: [docs/deployment.md](./deployment.md)
- Related: [docs/testing.md](./testing.md)
- Related: [docs/authentication.md](./authentication.md)
