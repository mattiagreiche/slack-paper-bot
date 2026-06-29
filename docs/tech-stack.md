# Tech Stack

> **AI Context Summary**: This is a Python 3.11+ FastAPI application with SQLAlchemy persistence, Jinja templates, light vanilla JavaScript, Docker Compose Postgres, and pytest tests. Dependencies live in `pyproject.toml`; Docker Compose is the closest match to the intended runtime. Keep additions aligned with this small-stack shape.

## Overview

The stack is intentionally boring. There is no React/Next frontend, no task queue service, no Alembic migration layer yet, and no separate search service. The first Zotero integration should fit the current FastAPI/service/worker structure unless a spec change demands more.

## Key Concepts

- **Project package** — `slack-paper-archive` in `pyproject.toml:1`.
- **Python requirement** — Python 3.11+ (`pyproject.toml:4`).
- **Web framework** — FastAPI and Uvicorn (`pyproject.toml:7`).
- **Persistence** — SQLAlchemy with psycopg for Postgres (`pyproject.toml:9`).
- **Templates** — Jinja2 and static assets mounted by FastAPI (`app/main.py:26`).
- **HTTP clients** — httpx for Slack, arXiv, Crossref, and future scholarly APIs (`pyproject.toml:11`).
- **Settings** — pydantic-settings reads `.env` (`app/config.py:4`).
- **Tests** — pytest and respx optional dev dependencies (`pyproject.toml:17`).

## Runtime Services

Docker Compose defines:

- `db`: Postgres 16 with healthcheck (`docker-compose.yml:2`)
- `api`: FastAPI app on port 8000 (`docker-compose.yml:18`)
- `worker`: metadata refresh and Slack catch-up loop (`docker-compose.yml:36`)

Both `api` and `worker` mount the repo into `/app`, so code edits are visible during Docker development.

## Backend Libraries

FastAPI route handlers use dependency injection for database sessions (`app/main.py:78`). SQLAlchemy models use typed `Mapped` columns (`app/models.py:30`). External calls are async where they happen inside request or metadata paths.

When adding Zotero or Semantic Scholar integration, prefer a dedicated service module rather than mixing external API calls into routes.

## Frontend Shape

The local UI is server-rendered. Templates live in `app/templates`; static JavaScript lives in `app/static`. Live search updates `/search/results` rather than reloading the whole page.

Do not add a separate frontend framework for the trial unless the product shape changes materially.

## Tooling

The project sets Ruff line length to 100 (`pyproject.toml:25`) but does not currently define a lint command. Tests are configured with `testpaths = ["tests"]` and `pythonpath = ["."]` (`pyproject.toml:21`).

## Cross-References

- Related: [docs/backend.md](./backend.md)
- Related: [docs/testing.md](./testing.md)
- Related: [docs/deployment.md](./deployment.md)
