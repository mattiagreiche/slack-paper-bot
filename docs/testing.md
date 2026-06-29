# Testing

> **AI Context Summary**: Tests use pytest with in-memory SQLite fixtures for fast service and web coverage. Run targeted tests for changed modules; full `pytest` is reserved for broad changes. Mock external HTTP behavior rather than calling Slack, arXiv, Crossref, Zotero, or Semantic Scholar in tests.

## Overview

The existing test suite covers arXiv normalization, ingestion, Slack parsing/signing, web behavior, BibTeX, search filters, and backfill helpers. Tests should focus on behavior and idempotency, especially around duplicate Slack events, repeated shares, and external API failures.

## Key Concepts

- **Pytest config** — `testpaths = ["tests"]`, `pythonpath = ["."]` (`pyproject.toml:21`).
- **SQLite fixture** — in-memory database with `StaticPool` (`tests/conftest.py:9`).
- **Database setup** — tests create all SQLAlchemy tables directly (`tests/conftest.py:16`).
- **HTTP mocking** — `respx` is available for async HTTP mocks (`pyproject.toml:19`).

## Targeted Test Commands

```bash
pytest tests/test_arxiv.py
pytest tests/test_ingestion.py
pytest tests/test_slack.py
pytest tests/test_web.py
pytest tests/test_bibtex.py
```

Use full `pytest` only when the change crosses route, model, service, and worker boundaries together.

## What To Test

For ingestion changes, test:

- Slack formatting variants such as `<https://...|label>` and raw URLs
- duplicate URLs in one message
- duplicate event IDs
- same paper shared in multiple messages
- unsupported links ignored or recorded according to spec

For Slack changes, test:

- signature failure paths
- ignored DMs, bot messages, and deleted messages
- edited message behavior if changed
- backfill with date bounds and thread replies

For Zotero sync work, add tests for:

- one canonical item maps to one Zotero item
- lazy channel collection creation
- `Bot notes` preserve human notes and omit debug details
- retries do not duplicate items, collections, notes, or tags
- external related paper failures do not block sync

## Fixture Pattern

Use the `db_session` fixture for model/service tests. It avoids Docker and keeps tests fast:

```python
# tests/conftest.py:9
@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", ...)
```

Avoid tests that depend on local `.env`, real Slack tokens, real arXiv timing, or Postgres-only behavior unless explicitly scoped as integration tests.

## External API Strategy

Use mocked responses for arXiv, Crossref, Slack, Zotero, and Semantic Scholar. Store enough response shape in tests to prove behavior, not full API payload realism.

When adding a new source extractor, test URL normalization separately from metadata fetch. Normalization should be pure and fast.

## Cross-References

- Related: [docs/database.md](./database.md)
- Related: [docs/backend.md](./backend.md)
- Related: [docs/api.md](./api.md)
