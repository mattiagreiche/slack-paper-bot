# Slack Paper Archive: Project Memory

## Product Intent

This project is a greenfield MVP for a Mila research group workflow: researchers often share arXiv and other paper links in Slack, and the PI had previously mentioned wanting a way to automatically categorize/archive them. The MVP should prove the value of a Slack-connected paper memory before asking for lab-wide adoption or Slack admin approval.

The product should feel like a quiet research utility, not a social feed and not an LLM demo. The first version is archive-only:

- Collect direct paper links from Slack.
- Deduplicate repeated shares.
- Store where each paper was shared.
- Search by title, author, abstract, category, channel, sharer, and date.
- Show duplicate/share counts without turning it into upvotes.
- Export usable BibTeX.

Explicitly out of scope for MVP:

- LLM summaries.
- LLM classification.
- Semantic search.
- Chatbot search.
- Weekly digests.
- Reading status, importance levels, likes, or social features.
- LinkedIn extraction unless the arXiv link appears directly in Slack text.
- Full-text PDF parsing.

The demo should be convincing even before real Slack approval. That is why the app has a local simulator at `/demo/slack`, which uses the same ingestion code as real Slack events.

## UX Direction

The UI should be web app-first. Slack is an ingestion source, not the primary interaction surface. Avoid Slack replies or noisy bot behavior.

Current surfaces:

- `/`: Search page with in-place live search.
- `/papers/{id}`: Paper detail page.
- `/demo/slack`: Tiny fake Slack-like message composer for local demos.
- `/status`: Small operator/status page.

Design tone:

- Dense, quiet, archival.
- Usable by researchers repeatedly.
- No landing page or marketing explanation.
- Avoid cards inside cards and decorative noise.
- Keep the simulator simple: channel, sender, text box, post button.

Important UX decisions already made:

- Search updates in-place through `/search/results`; no full page reload after typing.
- Default sort is `recent`; second option is `most shared`.
- Relevance sort was removed because we do not have a meaningful relevance model yet.
- Blank date filters mean all-time.
- BibTeX opens in a modal on the paper page, not a raw terminal-like text page.
- The raw `.bib` endpoint still exists for direct download/use.

## Architecture

Stack:

- Python/FastAPI.
- Server-rendered Jinja templates.
- Light vanilla JS.
- SQLAlchemy ORM.
- Postgres in Docker Compose.
- SQLite works for local direct `uvicorn` demos.
- Worker process for metadata refresh and scheduled catch-up.

Docker services:

- `api`: FastAPI web app.
- `db`: Postgres.
- `worker`: metadata refresh and Slack catch-up.

Core model split:

- A `Paper` is canonical.
- A `SlackMention` is one share of that paper in Slack.
- Multiple Slack mentions attach to one paper.

This is important because repeated Slack shares should increment duplicate/share count, not create duplicate paper rows.

## Important Files

- `app/main.py`: FastAPI routes, auth, web pages, Slack Events endpoint, demo simulator routes.
- `app/models.py`: SQLAlchemy tables.
- `app/services/ingestion.py`: Slack-like message ingestion, URL extraction, dedupe.
- `app/services/slack.py`: Slack signature verification, event conversion, API client, backfill.
- `app/services/metadata.py`: arXiv metadata refresh and retry behavior.
- `app/services/citations.py`: arXiv/Crossref-style BibTeX fetching.
- `app/services/search.py`: keyword/filter search.
- `app/extractors/arxiv.py`: arXiv URL normalization and arXiv API parsing.
- `app/demo_config.py`: fake local simulator channels/users.
- `app/demo_data.py`: demo metadata/BibTeX fixtures for known papers.
- `scripts/reset_demo.py`: clears local/demo data.
- `scripts/backfill_channel.py`: real Slack channel backfill by channel ID.
- `tests/`: pytest coverage.

`scripts/seed_demo.py` was intentionally deleted. It used to preload three sample papers, but the user disliked static default content. The demo should start empty and be populated through the simulator.

## Data Model Notes

Main tables:

- `papers`
- `paper_citations`
- `slack_mentions`
- `channels`
- `users`
- `ingestion_events`

`papers` stores metadata:

- source type/id, e.g. `arxiv`, `1706.03762`
- title
- authors as newline-separated text
- abstract
- categories as comma-separated text
- canonical URL
- PDF URL
- metadata status/error/retry fields

`paper_citations` stores preferred BibTeX:

- paper ID
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

`ingestion_events` makes Slack/demo/backfill ingestion idempotent.

Current schema is created via `Base.metadata.create_all`. There are no Alembic migrations yet. That is acceptable for the current prototype but should change before a persistent deployment.

## arXiv Handling

MVP supports direct arXiv URLs:

- `https://arxiv.org/abs/<id>`
- `https://arxiv.org/pdf/<id>.pdf`

Version suffixes are normalized:

- `2401.12345v2` becomes `2401.12345`
- old IDs like `hep-th/9901001v3` become `hep-th/9901001`

Metadata source:

- arXiv Atom API: `https://export.arxiv.org/api/query?id_list=<id>`

Citation source:

arXiv’s own page uses `static/browse/.../js/cite.js`. The behavior discovered from that file:

- If the arXiv HTML page has `citation_doi`, arXiv’s button asks Crossref via `https://dx.doi.org/<doi>` with `Accept: application/x-bibtex`.
- Otherwise the button calls `https://arxiv.org/bibtex/<arxiv-id>`.

The app mirrors that in `app/services/citations.py`:

- Try arXiv-page DOI + Crossref when available.
- Otherwise use arXiv `/bibtex/{id}`.
- Store result in `paper_citations`.
- Fall back to locally generated BibTeX if citation fetching fails.

arXiv API pacing:

- `ARXIV_REQUEST_DELAY_SECONDS=3` default.
- This exists to respect arXiv public API rate guidance.

## Search Behavior

Search supports:

- free text
- channel
- user/sharer
- category
- from/to date
- sort: recent or most shared

Postgres uses full-text search through `to_tsvector`/`plainto_tsquery`. SQLite uses `ILIKE`-style fallback for local testing.

Live search:

- Page initially renders full search page.
- `app/static/search.js` listens to inputs/selects.
- After 350ms of no typing, it fetches `/search/results`.
- Only `#results-list` and `#result-count` update.
- Browser URL updates via `history.replaceState`, but focus stays in the input.

## Demo Simulator

Route:

- `GET /demo/slack`
- `POST /demo/slack`

Fake channels/users live in `app/demo_config.py`.

Simulator behavior:

1. User chooses fake channel and fake sender.
2. User types a message containing an arXiv link.
3. App builds a `SlackMessage`.
4. App calls the same `ingest_slack_message` function used for real Slack/backfill.
5. App applies demo fixtures for known IDs if available.
6. App tries one metadata refresh for new pending arXiv links.

This makes the local demo show the core workflow without needing Slack approval.

Known fixture papers in `app/demo_data.py`:

- `1706.03762`
- `2309.08600`
- `2406.09246`

These are not shown in the UI anymore. They are only used to make those demo links fill immediately/offline.

## Slack Integration Status

It is mostly wired, but real Slack still needs setup and a little polish.

Implemented:

- `/slack/events` endpoint.
- Slack signing secret verification.
- URL verification response.
- Message event handling.
- Ignores DMs via channel type filter.
- Ignores deleted messages and bot messages.
- Supports channel/group events in principle.
- Backfill script using Slack Web API.
- Worker scheduled catch-up for channels already known.

Required env vars:

- `SLACK_SIGNING_SECRET`
- `SLACK_BOT_TOKEN`

Slack app setup needed:

- Install Slack app in workspace.
- Set Events Request URL to public HTTPS endpoint ending in `/slack/events`.
- Subscribe to message events:
  - `message.channels`
  - `message.groups`
- Scopes likely needed:
  - `channels:history`
  - `channels:read`
  - `groups:history`
  - `groups:read`
  - `users:read`
- Bot must be invited to private channels.
- For public channels, invitation should be treated as opt-in.

Important caveat:

Live Slack Events may only provide user IDs and channel IDs, not pretty names. Backfill gets channel info, but user display-name enrichment is currently shallow. A good next step before a real Slack demo is to enrich users/channels via Slack API so the UI does not show raw IDs.

Another caveat:

The Events API handler does not currently fetch permalinks for live events. Backfill does. Add `chat.getPermalink` in live path if Slack links on detail pages matter for real Slack demos.

## Deployment Notes

Local direct server:

```bash
uvicorn app.main:app --reload
```

Direct local mode uses SQLite by default unless `DATABASE_URL` is set.

Docker:

```bash
docker compose up --build
```

Docker runs Postgres and the worker. This is closer to the intended deployment.

Docker is not installed in the current local environment where Codex has been working, so Compose has not been fully run here.

For Slack Events local testing, a public HTTPS tunnel is needed, e.g. ngrok/cloudflared, pointing to local port 8000.

## Auth and Privacy

MVP auth is a shared lab password:

- `SHARED_PASSWORD`
- signed cookie via `APP_SECRET_KEY`

This is intentionally low-friction for a demo. It is not enough for real production if private-channel metadata is included.

Privacy choices:

- Store paper metadata.
- Store channel/user/timestamp/permalink metadata.
- Do not store full Slack message excerpts.

Future real deployment should consider:

- lab allowlist login
- OAuth or institutional SSO
- per-channel visibility rules
- deletion/removal handling

## Tests

Run:

```bash
pytest
```

Current tests cover:

- arXiv URL normalization
- arXiv Atom parsing
- Slack link parsing
- ingestion dedupe
- search filters
- blank date handling
- live search partial endpoint
- demo Slack path
- demo fixtures storing arXiv-style BibTeX
- `.bib` route

Known warnings:

- FastAPI `on_event` deprecation.
- Starlette template calling convention deprecation.
- TestClient per-request cookie warning.

These are not behavior blockers but are good cleanup tasks.

## Likely Next Tasks

Highest value before showing someone:

1. Real Slack polish:
   - Fetch user display names.
   - Fetch channel names for live events.
   - Fetch permalinks for live events.
   - Confirm Events API payload shape in a real workspace.

2. Demo flow polish:
   - After posting in `/demo/slack`, redirect to search or show a small success state.
   - Maybe add a button from simulator to “View archive.”

3. Metadata reliability:
   - Make citation fetch failure visible but non-blocking.
   - Add a status count for pending metadata only; failed metadata was removed from UI by user request.

4. Database lifecycle:
   - Add Alembic before persistent production data.

5. Search quality:
   - Better ranking later.
   - Semantic search later with pgvector, but not MVP.

6. New sources:
   - OpenReview.
   - DOI links.
   - ACL Anthology.
   - Semantic Scholar.

## User Preferences Captured

- Wants MVP archive only.
- Wants web app-first.
- No Slack clutter or bot replies.
- No “LLM slop” yet.
- No feed/social product vibes.
- Search should feel fluid and not steal focus.
- Static seeded sample papers should not appear by default.
- Demo simulator should be minimal.
- BibTeX should appear in a modal, not a raw text page.
- Status page should be simple and not overly technical.
- `Mentions` label felt unclear; changed to `Papers w/ dupes`.
- Failed metadata was removed from the status page.

