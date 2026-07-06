# Slack Paper Archive

A small FastAPI app that saves scholarly links shared in opted-in public Slack channels and syncs them into a Zotero group library. It supports arXiv, DOI resolver, and Semantic Scholar paper links, stores one canonical paper record, and records each Slack share as provenance for the Zotero item.

The current MVP gives you:

- Slack Events ingestion for new public channel messages.
- Backfill for channels the bot has joined.
- arXiv, DOI/Crossref, and Semantic Scholar metadata.
- Zotero group item sync, channel-based collections, and bot-owned provenance notes.
- Operator status queues with metadata/Zotero retry controls.
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
ZOTERO_API_KEY=
ZOTERO_GROUP_ID=
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
```

In **OAuth & Permissions**, add bot token scopes:

```text
channels:history
channels:read
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

Post an arXiv, DOI resolver, or Semantic Scholar paper link. New events should appear in the archive.

The trial intentionally ignores private channels. Public channels are opt-in by inviting the bot.

## Zotero Setup

Create or choose a Zotero group library, then create a Zotero API key with write access to that group. Put these in `.env`:

```bash
ZOTERO_API_KEY=...
ZOTERO_GROUP_ID=...
```

`ZOTERO_GROUP_ID` is the numeric ID in the Zotero group library URL. Restart Docker after changing these values:

```bash
docker compose down
docker compose up --build
```

Once a paper has metadata, the worker creates a Zotero item in the group library, lazily creates a collection for the Slack channel, and writes one child note titled `Bot notes` with the Slack share history.

## Operator Status

Open `/status` after logging in to inspect:

- pending and failed metadata work
- pending and failed Zotero sync work
- recent ingestion events
- channel backfill and catch-up timestamps

Retry buttons reset failed metadata or Zotero sync state so the worker can try again immediately. Displayed errors are redacted before rendering.

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

Backfill every public channel the bot has joined:

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

## Supported Link Sources

Supported direct links:

- `https://arxiv.org/abs/<id>`
- `https://arxiv.org/pdf/<id>.pdf`
- `https://doi.org/<doi>`
- `https://dx.doi.org/<doi>`
- `https://www.semanticscholar.org/paper/.../<paper-id>`

The first trial still does not ingest arbitrary news/web pages. Publisher and journal pages need a later metadata-resolution layer unless the Slack message includes a DOI resolver link directly.

## Metadata And BibTeX

The app fetches arXiv metadata from:

```text
https://export.arxiv.org/api/query?id_list=<arxiv-id>
```

DOI metadata comes from Crossref:

```text
https://api.crossref.org/works/<doi>
```

Semantic Scholar paper metadata comes from:

```text
https://api.semanticscholar.org/graph/v1/paper/<paper-id>
```

The app does not download PDFs.

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
- `app/services/operator.py`: status helpers, retry state reset, error redaction.
- `app/services/search.py`: keyword and filter search.
- `app/extractors/arxiv.py`: arXiv URL normalization and Atom parsing.
- `app/extractors/doi.py`: DOI resolver normalization and Crossref parsing.
- `app/extractors/semantic_scholar.py`: Semantic Scholar paper URL normalization and Graph API parsing.
- `scripts/reset_archive.py`: clears stored data.
- `scripts/backfill_joined_channels.py`: backfills joined Slack channels.
- `scripts/backfill_channel.py`: backfills one Slack channel.
- `CODEX.md`: design notes and current project memory.

## Tests

```bash
pytest
```

The tests cover arXiv/DOI/Semantic Scholar normalization, Slack event parsing, dedupe, search filters, BibTeX, Zotero sync, operator retries, and backfill helpers.
