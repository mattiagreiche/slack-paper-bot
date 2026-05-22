# Slack Paper Archive

A small FastAPI app that saves paper links shared in Slack. It starts with arXiv links, stores one canonical paper record, and records each Slack share as a separate mention.

The current MVP gives you:

- Slack Events ingestion for new channel messages.
- Backfill for channels the bot has joined.
- arXiv metadata and arXiv/Crossref-style BibTeX.
- Search by paper text, channel, sharer name, date, and share count.
- Shared-password access.

## Run With Docker

Install Docker Desktop, then create your local env file:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
APP_SECRET_KEY=replace-with-a-random-secret
SHARED_PASSWORD=papers
SLACK_SIGNING_SECRET=
SLACK_BOT_TOKEN=
```

Generate a secret if you want one:

```bash
openssl rand -hex 32
```

Start the app:

```bash
docker compose up --build
```

Open:

```text
http://localhost:8000
```

Log in with `SHARED_PASSWORD`.

Clear local data:

```bash
docker compose exec api python scripts/reset_archive.py
```

Delete the whole Postgres volume:

```bash
docker compose down -v
```

## Slack Setup

Create a Slack app in your test workspace.

In **Event Subscriptions**:

```text
Request URL: https://your-tunnel-or-domain/slack/events
```

Subscribe to bot events:

```text
message.channels
message.groups
```

In **OAuth & Permissions**, add bot token scopes:

```text
channels:history
channels:read
groups:history
groups:read
users:read
```

Install or reinstall the app. Slack only grants new scopes after reinstall.

Copy the values into `.env`:

```bash
SLACK_SIGNING_SECRET=...
SLACK_BOT_TOKEN=xoxb-...
```

Restart Docker:

```bash
docker compose down
docker compose up --build
```

Invite the bot to a channel:

```text
/invite @your-bot-name
```

Post an arXiv link. New events should appear in the archive.

## Public Tunnel For Slack Testing

For local Slack testing, run the app in one terminal:

```bash
docker compose up --build
```

Run ngrok in another:

```bash
ngrok http 8000
```

Use the HTTPS ngrok URL as:

```text
https://your-ngrok-url/slack/events
```

You do not need to restart ngrok when you restart Docker, as long as it still points to port `8000`.

## Backfill

After a database reset, Slack will not resend old events. Run a backfill to read channel history.

Backfill every public/private channel the bot has joined:

```bash
docker compose exec api python scripts/backfill_joined_channels.py --limit 200
```

Backfill one channel by ID:

```bash
docker compose exec api python scripts/backfill_channel.py C0123456789 --limit 200
```

`--limit` means Slack messages per channel, not papers.

Add date bounds with UTC dates:

```bash
docker compose exec api python scripts/backfill_joined_channels.py --since 2026-05-01 --until 2026-05-22 --limit 1000
docker compose exec api python scripts/backfill_channel.py C0123456789 --since 2026-05-01 --limit 1000
```

The worker catches up channels already known to the database. A blank database has no channel list, so run joined-channel backfill once after resets.

## arXiv And BibTeX

The app fetches metadata from:

```text
https://export.arxiv.org/api/query?id_list=<arxiv-id>
```

It does not download PDFs.

For BibTeX, the app mirrors arXiv’s export button:

- If the arXiv page exposes a DOI, ask Crossref for `application/x-bibtex`.
- Otherwise call `https://arxiv.org/bibtex/<arxiv-id>`.
- Fall back to locally generated BibTeX if fetching fails.

The worker uses `ARXIV_REQUEST_DELAY_SECONDS=3` by default.

## Development Without Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

The non-Docker default database is:

```text
sqlite:///./paper_archive.db
```

Docker uses Postgres and matches the intended deployment shape.

## Project Map

- `app/main.py`: routes, auth, web pages, Slack Events endpoint.
- `app/models.py`: SQLAlchemy tables.
- `app/services/ingestion.py`: URL parsing, message ingestion, dedupe.
- `app/services/slack.py`: Slack signature checks, Web API client, backfill.
- `app/services/metadata.py`: arXiv metadata refresh.
- `app/services/citations.py`: arXiv/Crossref BibTeX fetch.
- `app/services/search.py`: keyword and filter search.
- `app/extractors/arxiv.py`: arXiv URL normalization and Atom parsing.
- `scripts/reset_archive.py`: clears stored data.
- `scripts/backfill_joined_channels.py`: backfills joined Slack channels.
- `scripts/backfill_channel.py`: backfills one Slack channel.
- `CODEX.md`: design notes and current project memory.

## Tests

```bash
pytest
```

The tests cover arXiv normalization, Slack event parsing, dedupe, search filters, BibTeX, and backfill helpers.
