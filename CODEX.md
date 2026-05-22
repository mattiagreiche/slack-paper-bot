# Slack Paper Archive: Project Memory

## Product Intent

This project archives papers shared in Slack for a research group. The user now has a test Slack workspace, so the app should use real Slack Events and real backfill for demos. Do not reintroduce the old fake Slack simulator.

MVP scope:

- Ingest direct paper links from Slack.
- Start with arXiv.
- Deduplicate repeated shares.
- Store each Slack share as a mention on one canonical paper.
- Search by paper text, channel, sharer name, date, and share count.
- Export BibTeX.

Keep out of MVP:

- LLM summaries or classification.
- Semantic search.
- Chatbot search.
- Weekly digests.
- Reading status, importance levels, likes, or social behavior.
- LinkedIn scraping.
- Full-text PDF parsing.

## UX Direction

The UI should feel like a quiet research utility. Slack sends data in; the web app lets people find it.

Current surfaces:

- `/`: Search page with in-place live search.
- `/papers/{id}`: Paper detail page.
- `/status`: Small status page.
- `/login`: Shared-password gate.

Decisions already made:

- Search updates through `/search/results`; no full page reload while typing.
- Default sort is `recent`.
- Secondary sort is `most shared`.
- Relevance sort was removed.
- Blank date filters mean all-time.
- Category filter and category tags were removed from the main search page.
- Sharer filter is a text input, not a dropdown.
- BibTeX opens in a modal on the paper page.
- Raw `.bib` endpoint stays available.

## Architecture

Stack:

- Python/FastAPI.
- Jinja templates.
- Light vanilla JS.
- SQLAlchemy ORM.
- Postgres in Docker Compose.
- SQLite for direct local `uvicorn` work.
- Worker process for metadata refresh and Slack catch-up.

Docker services:

- `api`: FastAPI web app.
- `db`: Postgres.
- `worker`: metadata refresh and channel catch-up.

Core model:

- `Paper` is canonical.
- `SlackMention` records one Slack share.
- Many mentions can point at one paper.

## Important Files

- `app/main.py`: routes, auth, search pages, Slack Events endpoint.
- `app/models.py`: SQLAlchemy tables.
- `app/services/ingestion.py`: URL parsing, message ingestion, dedupe.
- `app/services/slack.py`: Slack signature checks, Web API client, event/backfill helpers.
- `app/services/metadata.py`: arXiv metadata refresh.
- `app/services/citations.py`: arXiv/Crossref BibTeX fetch.
- `app/services/search.py`: keyword and filter search.
- `app/extractors/arxiv.py`: arXiv URL normalization and Atom parsing.
- `scripts/reset_archive.py`: clears stored archive data.
- `scripts/backfill_joined_channels.py`: backfills channels the bot has joined.
- `scripts/backfill_channel.py`: backfills one Slack channel.

Deleted on purpose:

- `scripts/seed_demo.py`
- `app/demo_config.py`
- `app/demo_data.py`
- `app/templates/demo_slack.html`

## Data Model Notes

Tables:

- `papers`
- `paper_citations`
- `slack_mentions`
- `channels`
- `users`
- `ingestion_events`

`papers` stores arXiv metadata and retry state.

`paper_citations` stores preferred BibTeX:

- BibTeX text
- provider
- source URL
- fetched timestamp

`slack_mentions` stores:

- paper ID
- team/channel/user IDs
- channel/user display names when known
- Slack timestamp/thread timestamp
- original URL
- permalink when known
- posted timestamp

`ingestion_events` makes Slack/backfill ingestion idempotent.

There are no Alembic migrations yet. Add migrations before using persistent production data.

## arXiv Handling

Supported URLs:

- `https://arxiv.org/abs/<id>`
- `https://arxiv.org/pdf/<id>.pdf`

Normalization:

- `2401.12345v2` becomes `2401.12345`.
- `hep-th/9901001v3` becomes `hep-th/9901001`.

Metadata source:

```text
https://export.arxiv.org/api/query?id_list=<id>
```

BibTeX behavior mirrors arXiv’s export button:

- If the arXiv page exposes `citation_doi`, ask Crossref with `Accept: application/x-bibtex`.
- Otherwise call `https://arxiv.org/bibtex/<arxiv-id>`.
- Fall back to locally generated BibTeX if fetch fails.

The worker uses `ARXIV_REQUEST_DELAY_SECONDS=3`.

## Search Behavior

Search supports:

- free text
- channel
- sharer text
- from/to date
- recent or most-shared sort

Postgres uses full-text search through `to_tsvector` and `plainto_tsquery`. SQLite uses `ILIKE`-style fallback.

Live search:

- `app/static/search.js` listens to inputs/selects.
- After 350ms of no typing, it fetches `/search/results`.
- It updates `#results-list` and `#result-count`.
- It updates the browser URL with `history.replaceState`.
- Input focus stays put.

## Slack Integration

Implemented:

- `/slack/events`.
- Slack signing secret verification.
- URL verification.
- `message.channels` and `message.groups`.
- DM filtering via channel type.
- Deleted-message and bot-message ignore rules.
- Slack Web API enrichment for channel names, user names, and permalinks.
- Backfill by one channel.
- Backfill all joined channels.
- Worker catch-up for channels already known to the DB.

Required env vars:

- `SLACK_SIGNING_SECRET`
- `SLACK_BOT_TOKEN`

Slack bot scopes:

- `channels:history`
- `channels:read`
- `groups:history`
- `groups:read`
- `users:read`

After scope changes, reinstall the Slack app.

Operational pattern:

1. Invite bot to channels.
2. Post new links and let Events API ingest them.
3. After reset or first setup, run:

```bash
docker compose exec api python scripts/backfill_joined_channels.py --limit 200
```

Use date bounds for larger workspaces:

```bash
docker compose exec api python scripts/backfill_joined_channels.py --since 2026-05-01 --until 2026-05-22 --limit 1000
```

## Deployment Notes

Docker:

```bash
docker compose up --build
```

For local Slack testing, run ngrok:

```bash
ngrok http 8000
```

Use:

```text
https://your-ngrok-url/slack/events
```

Docker persists Postgres data in the `postgres_data` volume. These commands clear data:

```bash
docker compose exec api python scripts/reset_archive.py
docker compose down -v
```

## Auth And Privacy

MVP auth uses:

- `SHARED_PASSWORD`
- signed cookie via `APP_SECRET_KEY`

The app stores paper metadata and Slack metadata. It does not store full Slack message excerpts.

Real deployment should add:

- lab allowlist login
- OAuth or SSO
- per-channel visibility rules
- backups
- migrations

## Tests

Run:

```bash
pytest
```

Current tests cover:

- arXiv URL normalization.
- arXiv Atom parsing.
- Slack event parsing.
- Slack enrichment.
- ingestion dedupe.
- search filters.
- blank date handling.
- live search partial endpoint.
- stored BibTeX preference.
- `.bib` route.
- joined-channel backfill helper.

Known warnings:

- FastAPI `on_event` deprecation.
- TestClient per-request cookie warning.

## Likely Next Tasks

Good next steps:

- Improve status page wording as the product settles.
- Add Alembic migrations.
- Add database backups before any real deployment.
- Add OpenReview/DOI/ACL sources.
- Add semantic search later with pgvector.

## User Preferences Captured

- Wants archive-only MVP.
- Wants web app-first.
- Wants real Slack test workspace for demo.
- No fake Slack simulator.
- No Slack clutter or bot replies.
- No LLM features yet.
- No feed/social product feel.
- Search should feel fluid and keep focus.
- Static sample papers should not appear.
- BibTeX should appear in a modal.
- Status page should stay simple.
- `Mentions` label changed to `Papers w/ dupes`.
- Failed metadata was removed from the status page.

