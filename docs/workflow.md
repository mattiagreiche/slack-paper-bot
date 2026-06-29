# Agentic Workflow

> **AI Context Summary**: This repo has project-specific planner and builder agents under `.codex/agents/`. Use planner agents for design decomposition and builder agents for bounded implementation slices. Keep write scopes disjoint when parallelizing, and run targeted tests before integration.

## Overview

The workflow is spec-driven. The main behavioral spec is `specs/zotero-integrated-paper-archive.md`; the glossary is `specs/glossary.md`. The planner turns feature requests into implementation tasks. The builder executes tasks exactly as specified.

Agents should reference docs rather than loading all context at once. `AGENTS.md` is the always-on guide; `docs/` is progressive disclosure.

## Key Concepts

- **Planner agent** — `.codex/agents/planner.toml`
- **Builder agent** — `.codex/agents/builder.toml`
- **Project guide** — `AGENTS.md`
- **Behavioral spec** — `specs/zotero-integrated-paper-archive.md`
- **Project memory** — `CODEX.md`

## Planning Pattern

Use planner agents when a task needs design decisions, dependency boundaries, or decomposition. Planner output should include scope, file paths, state management, error strategy, dependency design, and tests.

Do not ask builders to decide architecture. If a builder reports a blocker, route that decision back through the main agent or planner.

## Builder Pattern

Use builder agents for bounded implementation slices. Assign file ownership clearly. Good slices are things like:

- Zotero API client and tests
- Zotero sync state models and tests
- Bot-Owned Note rendering and tests
- Semantic Scholar recommendation service and tests

Avoid parallel builders touching the same shared files unless the tasks are sequenced.

## Review And Testing

Builders must run targeted tests for their changed files. The builder instructions include a `$reviewing-code-quality` gate; use it before accepting builder output when that skill is available.

## Cross-References

- Related: [docs/architecture.md](./architecture.md)
- Related: [docs/testing.md](./testing.md)
- Related: [docs/backend.md](./backend.md)
