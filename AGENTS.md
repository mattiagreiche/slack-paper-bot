# Project Context

**Mission:** Archive scholarly links shared in Slack and sync useful paper records into Zotero for a research group.

Slack Paper Archive is a Python web app with Slack ingestion, local review/search, metadata enrichment, and a planned Zotero-centered trial. Build from the behavioral spec, not from old demo assumptions.

## About This Project

The app uses FastAPI, Jinja, vanilla JavaScript, SQLAlchemy, Postgres in Docker Compose, SQLite for local direct runs, and pytest. The current product direction is Zotero-first: the local web app supports ingestion, sync status, retry/review, and secondary search.

## Key Directories

- `app/` — FastAPI app, models, services, extractors, templates, static assets
- `app/services/` — ingestion, Slack API/backfill, metadata, citations, search
- `app/extractors/` — source-specific URL normalization and metadata fetch logic
- `scripts/` — operator commands for reset and Slack backfill
- `tests/` — pytest coverage for extractors, ingestion, Slack, web, search, BibTeX
- `specs/` — behavioral source of truth for the Zotero trial
- `docs/` — detailed architecture, setup, testing, deployment, workflow references
- `.codex/agents/` — project planner and builder agents

## Commands

```bash
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"  # local setup
uvicorn app.main:app --reload                                                   # local dev server
docker compose up --build                                                       # Docker app + worker + Postgres
pytest tests/test_ingestion.py                                                  # targeted tests
docker compose exec api python scripts/backfill_joined_channels.py --limit 200  # Slack backfill
```

## Standards

- Follow `specs/zotero-integrated-paper-archive.md` for Slack-to-Zotero behavior.
- Keep changes scoped; match existing FastAPI, SQLAlchemy, Jinja, service, and pytest patterns.
- Make ingestion/sync idempotent; retries must not create duplicate papers, mentions, Zotero items, notes, tags, or collections.
- Treat Slack, Zotero, arXiv, Crossref, and Semantic Scholar as unreliable external dependencies.
- Never store full Slack message text or expose secrets in pages, logs, errors, tests, or Zotero notes.
- Do not overwrite human-authored Zotero notes, tags, collections, or item edits.
- Do not reintroduce the deleted fake Slack simulator.

## Notes

- There are no Alembic migrations yet; schema changes need an explicit persistence plan.
- Private Slack channels are excluded from the Zotero trial.
- External related papers are suggestions only; do not auto-import them into Zotero.
- Use [CODEX.md](/Users/mattiagreiche/Projects/slack-paper-bot/CODEX.md) for project memory and recent decisions.

## Workflow

When implementing multi-part features:

1. Use the planner subagent for design work when the user asks for agentic planning.
2. Sequence tasks that touch shared files such as `app/models.py`, `app/main.py`, or shared templates.
3. Use builder subagents for independent implementation slices with disjoint write sets.
4. Run targeted tests for each slice before integration.

## Additional Documentation

Before specific tasks, read only the relevant docs:

- Architecture: [docs/architecture.md](/Users/mattiagreiche/Projects/slack-paper-bot/docs/architecture.md)
- Backend/API: [docs/backend.md](/Users/mattiagreiche/Projects/slack-paper-bot/docs/backend.md), [docs/api.md](/Users/mattiagreiche/Projects/slack-paper-bot/docs/api.md)
- Data model: [docs/database.md](/Users/mattiagreiche/Projects/slack-paper-bot/docs/database.md)
- Testing: [docs/testing.md](/Users/mattiagreiche/Projects/slack-paper-bot/docs/testing.md)
- Setup/deployment: [docs/getting-started.md](/Users/mattiagreiche/Projects/slack-paper-bot/docs/getting-started.md), [docs/deployment.md](/Users/mattiagreiche/Projects/slack-paper-bot/docs/deployment.md)
- Agent workflow: [docs/workflow.md](/Users/mattiagreiche/Projects/slack-paper-bot/docs/workflow.md)
