# Documentation Index

> **AI Context Summary**: This index routes agents to the smallest useful project document. Start with `AGENTS.md`, then read only the docs that match the task. The Zotero trial spec remains the behavioral source of truth.

## Overview

Slack Paper Archive is a FastAPI app that ingests scholarly links from Slack and is moving toward Zotero as the primary shared library interface. Documentation is split by task area so agents can load context progressively.

## Core Docs

- [Architecture](./architecture.md) — runtime structure, data flow, service boundaries
- [Getting Started](./getting-started.md) — local setup, Docker, Slack tunnel, backfill
- [Tech Stack](./tech-stack.md) — frameworks, libraries, runtime services
- [Testing](./testing.md) — pytest strategy, fixtures, targeted commands
- [Database](./database.md) — SQLAlchemy models, idempotency, schema cautions
- [Backend](./backend.md) — route/service/worker patterns
- [API And Routes](./api.md) — local pages, JSON partials, Slack webhook
- [Authentication](./authentication.md) — shared password, Slack signatures, secrets
- [Deployment](./deployment.md) — Docker Compose, VM shape, public URL needs
- [Security](./security.md) — privacy and credential boundaries
- [Agentic Workflow](./workflow.md) — planner/builder usage

## Specs

- [Zotero trial spec](../specs/zotero-integrated-paper-archive.md)
- [Domain glossary](../specs/glossary.md)

## How To Choose

For Slack ingestion, read Architecture, Backend, API, and Testing.  
For Zotero sync, read Architecture, Database, Backend, Security, and the Zotero trial spec.
For related-paper generation, read Architecture, Backend, Database, Security, Testing, and the Zotero trial spec.
For deployment questions, read Getting Started and Deployment.  
For auth or privacy changes, read Authentication and Security.  
For agent orchestration, read Agentic Workflow.

## Cross-References

- Related: [../AGENTS.md](../AGENTS.md)
- Related: [../CODEX.md](../CODEX.md)
