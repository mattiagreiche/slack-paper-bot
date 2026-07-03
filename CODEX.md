# Slack Paper Archive: Project Memory

## Product Intent

This project archives papers shared in Slack for a research group. The user now has a test Slack workspace, so the app should use real Slack Events and real backfill for demos. Do not reintroduce the old fake Slack simulator.

Current product direction has shifted toward a Zotero-integrated trial:

- Zotero should be the primary shared library interface.
- The local web app should become the Slack ingestion, sync status, retry, dry-run, and review surface.
- Local archive search may remain as a secondary/fallback view if Zotero search is insufficient, but it should not be the primary homepage by default.
- First working Zotero milestone: Slack arXiv link in an opted-in public channel -> Zotero item -> auto-created channel collection -> `Bot notes` with Slack provenance.
- Full trial spec still includes journal article/publisher page resolution, generated related papers, generated topic tags, and dry-run plus real Zotero sync.
- Trial excludes private channels and general webpages/news/ResearchGate links unless they resolve to stable scholarly identifiers.
- Real Zotero sync matters more than dry-run because the user can test with a personal/trial Zotero library. If dry-run is implemented, item-level preview is enough.
- First build plain Slack-to-Zotero sync: item, channel collection, and `Bot notes` with Slack provenance.
- Add generated curation after the plain sync path works. Once enabled, generated curation can run on first sync when enough metadata exists; later refreshes should be explicit operator actions.
- Zotero writes should happen immediately and use failure recording/retry rather than approval batches or heavy rate-limit UI.
- Secondary local archive search can remain available to trial viewers if it runs on the same deployment without making operations meaningfully harder.
- Zotero channel collections should be created lazily when the first supported item from that channel syncs.
- Bot-Owned Notes should contain only human-useful content, not debug IDs or retry details.
- Unsupported links from opted-in public channels can be visible in the local surface, but they should not create Zotero items.
- External related papers are the useful related-paper feature for now: broader scholarly recommendations from an outside discovery source.
- Internal related papers mean similar items already in the trial library/Zotero corpus; defer this for the trial.
- External related papers can likely use a scholarly recommendation API such as Semantic Scholar, if available and reliable, and should appear in Zotero `Bot notes`.
- External related papers should be suggestions only during the trial, not automatically imported into Zotero. A later manual "add to Zotero" action is useful.
- Show up to five external related papers per item. If recommendations are unavailable, say related papers are unavailable in `Bot notes`.
- A manually imported external related paper should go into the same Zotero channel collection as the paper it was suggested from.
- Generated tags should start rule-based after external related papers work: arXiv categories, fields of study, venue/type metadata, and similar structured scholarly metadata. Avoid making an LLM required for tags.

The current behavioral spec lives at:

- `specs/zotero-integrated-paper-archive.md`
- `specs/glossary.md`

MVP scope:

- Ingest direct paper links from Slack.
- Support arXiv, DOI resolver, and Semantic Scholar paper links.
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
- `app/services/zotero.py`: Zotero group item sync, collection mapping, and bot-owned provenance notes.
- `app/extractors/arxiv.py`: arXiv URL normalization and Atom parsing.
- `app/extractors/doi.py`: DOI resolver normalization and Crossref metadata parsing.
- `app/extractors/semantic_scholar.py`: Semantic Scholar paper URL normalization and Graph API parsing.
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
- `zotero_collection_syncs`
- `zotero_item_syncs`

`papers` stores source metadata and retry state for arXiv, DOI/Crossref, and Semantic Scholar items.

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

## DOI And Semantic Scholar Handling

Supported DOI URLs:

- `https://doi.org/<doi>`
- `https://dx.doi.org/<doi>`

DOI normalization lowercases the DOI and strips common trailing punctuation. Metadata comes from:

```text
https://api.crossref.org/works/<doi>
```

Supported Semantic Scholar URLs:

- `https://www.semanticscholar.org/paper/.../<paper-id>`

Semantic Scholar metadata comes from:

```text
https://api.semanticscholar.org/graph/v1/paper/<paper-id>
```

Current limitation: DOI links and Semantic Scholar links to the same underlying paper are not merged cross-source yet. Publisher/journal pages are still not resolved unless the posted URL itself is a DOI resolver or recognized Semantic Scholar paper URL.

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
- `message.channels`.
- DM/private-channel filtering via channel type.
- Deleted-message and bot-message ignore rules.
- Slack Web API enrichment for channel names, user names, and permalinks.
- Backfill by one channel.
- Backfill all joined channels.
- Worker catch-up for channels already known to the DB.

Current trial behavior is public-channel only. Private Slack channels are intentionally ignored even if Slack credentials could read them.

Verified in the user's real test Slack workspace:

- Slack Events ingestion received a posted paper link.
- Channel enrichment returned a readable channel name.
- The bot/app install, ngrok Request URL, Docker app, and Slack signing/token setup have worked together.
- User-name enrichment was added after the first live test; if a user ID still appears, inspect Docker logs for a `users.info` scope/API failure and confirm `users:read` was granted before reinstalling the app.

Required env vars:

- `SLACK_SIGNING_SECRET`
- `SLACK_BOT_TOKEN`

Slack bot scopes:

- `channels:history`
- `channels:read`
- `users:read`

After scope changes, reinstall the Slack app.

## Zotero Integration

Implemented first vertical slice:

- Worker syncs metadata-ready public-channel papers to the configured Zotero group library.
- Missing channel collections are created lazily from the raw Slack channel name.
- One Zotero item is created per canonical paper.
- Existing Zotero items can be reused when the bot marker is found in `extra`.
- Existing bot-owned notes are reused when found under the item.
- The bot writes one child note titled `Bot notes` with Slack channel, sharer, date, Slack permalink, and shared link.
- Bot notes intentionally exclude full Slack message text, stack traces, retry details, and sync IDs.
- Private-channel-only papers are skipped for Zotero sync during the trial.
- Status page shows Zotero synced/failed counts.

Required Zotero env vars for real sync:

- `ZOTERO_API_KEY`
- `ZOTERO_GROUP_ID`

Optional Zotero env vars:

- `ZOTERO_API_BASE_URL`
- `ZOTERO_SYNC_LIMIT`

The worker runs metadata refresh first, then Zotero sync, then Slack catch-up. If Zotero env vars are absent, Zotero sync is a no-op.

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

Backfill details:

- `--limit` counts Slack messages per channel, not papers.
- Resetting the archive deletes stored channel knowledge. Slack does not replay old Events API deliveries, so run `backfill_joined_channels.py` after a reset.
- The worker performs incremental catch-up only for channels already stored in the database.

Resolved Slack/backfill bugs:

- Live Events plus backfill could count the same Slack message twice when one pass saw an `abs` URL and another saw a `pdf` URL, or when backfill lacked the workspace ID later provided by Events API. Mention dedupe now keys on channel, Slack message timestamp, and paper; a later live event fills in its workspace ID.
- One uncommitted backfill batch could queue the same channel/user insert multiple times and fail with a Postgres unique violation. Ingestion now reuses pending SQLAlchemy channel/user objects within the transaction.

On 2026-05-25, the local Docker Postgres database was repaired in place: one false duplicate mention was deleted and `uq_slack_mention` was updated to match the corrected identity. New databases get this constraint from `app/models.py`; add formal migrations before persistent deployment.

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

`docker compose down` followed by `docker compose up --build` should preserve papers. If the site shows no results while Postgres still contains a paper, check `slack_mentions` and clear any browser search filters first: the results query displays papers through their Slack mentions.

The user has used Docker Desktop and ngrok for Slack testing. Restart Docker after code or `.env` changes. Ngrok can stay running while Docker restarts as long as it still forwards to port `8000`.

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
- signed live Slack Events ingestion route.

Known warnings:

- FastAPI `on_event` deprecation.
- TestClient per-request cookie warning.

Resolved deployment issue:

- Docker installed a newer Starlette/FastAPI version than the direct local environment. Old `TemplateResponse("file.html", context)` calls crashed in Docker. Routes now use the request-first `TemplateResponse(request, "file.html", context)` form.
- Removing the fake Slack demo path also removed the import used by the real `/slack/events` handler, causing incoming events to fail with `NameError: ingest_slack_message`. The import is restored and a signed endpoint regression test now exercises real event ingestion.

## Likely Next Tasks

Good next steps:

- Improve status page wording as the product settles.
- Add Alembic migrations.
- Add database backups before any real deployment.
- Add publisher/journal page resolution, likely through Zotero translators or a dedicated metadata resolver.
- Add OpenReview/ACL sources.
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
