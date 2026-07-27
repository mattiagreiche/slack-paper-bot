# Slack Paper Archive

A small FastAPI app that saves scholarly links shared in opted-in public Slack channels and syncs them into a Zotero group library. It supports arXiv, DOI resolver, and Semantic Scholar paper links, stores one canonical paper record, and records each Slack share as provenance for the Zotero item.

The current MVP gives you:

- Slack Events ingestion for new public channel messages.
- Backfill for channels the bot has joined.
- arXiv, DOI/Crossref, and Semantic Scholar metadata.
- Zotero group item sync, channel-based collections, and bot-owned provenance notes.
- Optional Semantic Scholar related-paper suggestions in Zotero `Bot notes`.
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
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
SLACK_OAUTH_REDIRECT_URI=https://your-public-host/slack/oauth/callback
CREDENTIAL_ENCRYPTION_KEY=
```

Generate the Fernet encryption key:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
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

Ordinary reset: clear archive and derived sync data while preserving the Slack
Installation and Trial Zotero Destination:

```bash
docker compose exec api python scripts/reset_archive.py
```

F-13 adds encrypted installation tables without Alembic migrations. Before the
first OAuth test only, deliberately recreate the local schema:

```bash
docker compose down -v
docker compose up --build
```

This one-time pre-OAuth recreation deletes the entire Postgres volume,
including the archive and persisted credentials. It is not an ordinary reset.
Use `scripts/reset_archive.py` for routine cleanup.

## Slack Setup

Create a Slack app in your test workspace.

In **OAuth & Permissions**, set the redirect URL:

```text
https://your-tunnel-or-domain/slack/oauth/callback
```

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

Save the scope configuration. Workspace authorization happens through the
application's `/slack/install` OAuth flow below; after changing scopes, run
that flow again so Slack grants the updated set.

Copy the Slack app credentials into `.env`:

```bash
SLACK_SIGNING_SECRET=...
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_OAUTH_REDIRECT_URI=https://your-tunnel-or-domain/slack/oauth/callback
CREDENTIAL_ENCRYPTION_KEY=... # one stable Fernet key; see .env.example
```

Restart Docker:

```bash
docker compose down
docker compose up --build
```

Open `/slack/install` to authorize the workspace. A new installation remains
inactive until its Trial Zotero Destination is verified and an operator
activates it.

Invite the bot to a channel:

```text
/invite @your-bot-name
```

Post an arXiv, DOI resolver, or Semantic Scholar paper link. New events should appear in the archive.

The trial intentionally ignores private channels. Public channels are opt-in by inviting the bot.

### Temporary bot-token migration bridge

`SLACK_BOT_TOKEN` is not the supported installation path. Keep it only while
reauthorizing the existing test workspace:

```bash
SLACK_OAUTH_MIGRATION_MODE=true
SLACK_LEGACY_TEAM_ID=T0123456789
SLACK_BOT_TOKEN=xoxb-temporary
```

Delete all three values after the OAuth-installed test workspace has passed
both an Events API smoke test and a worker catch-up/backfill smoke test. Restart
the stack and repeat the checks with migration mode off before removing the
bridge variables and compatibility path from deployment/application config.

## Zotero Setup

Create or choose a Zotero group library, then create a Zotero API key with write
access to that group. Log in to the app, open `/status`, and enter the numeric
group ID and API key under **Trial destination**. Select **Verify and save**.

The verified destination is encrypted and persisted in Postgres; it is the sole
production credential source for API and worker operations. Do not put its
group ID or API key in `.env`. `ZOTERO_API_BASE_URL` remains an optional
deployment setting for changing the verification form's default API endpoint.

Once a paper has metadata, the worker creates a Zotero item in the group library, lazily creates a collection for the Slack channel, and writes one child note titled `Bot notes` with the Slack share history.

To add Semantic Scholar related-paper suggestions to `Bot notes`, enable the optional worker feature:

```bash
RELATED_PAPERS_ENABLED=true
RELATED_PAPERS_LIMIT=5
SEMANTIC_SCHOLAR_API_KEY=...  # optional, but useful for rate limits
```

Suggestions are stored locally and rendered as bot-generated external suggestions. They are not automatically imported into Zotero as separate library items.

## Operator Status

Open `/status` after logging in to inspect:

- pending and failed metadata work
- pending and failed Zotero sync work
- pending, unavailable, and failed related-paper work
- recent ingestion events
- channel backfill and catch-up timestamps

Retry buttons reset failed metadata, Zotero sync, or related-paper state so the worker can try again immediately. Displayed errors are redacted before rendering.

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
OAuth redirect:      https://your-ngrok-url/slack/oauth/callback
Event subscription: https://your-ngrok-url/slack/events
```

You do not need to restart ngrok when you restart Docker, as long as it still points to port `8000`.
If the ngrok hostname changes, update both Slack URLs and
`SLACK_OAUTH_REDIRECT_URI`, then restart the API before starting OAuth. The
callback URL exchanges an authorization code; `/slack/events` receives signed
event deliveries. They are not interchangeable.

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

The tests cover arXiv/DOI/Semantic Scholar normalization, Slack event parsing, dedupe, search filters, BibTeX, Zotero sync, related-paper suggestions, operator retries, and backfill helpers.
