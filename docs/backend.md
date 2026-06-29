# Backend

> **AI Context Summary**: Backend behavior is organized around thin FastAPI routes and service modules. Keep Slack, metadata, search, citation, and future Zotero logic in services; routes should authenticate, call services, and render responses. External dependencies are fallible and should be isolated at trust boundaries.

## Overview

`app/main.py` wires the app, routes, templates, and Slack Events endpoint. Most domain behavior lives below `app/services/` and `app/extractors/`.

The worker is a separate process that imports the same service modules. Shared service functions therefore need to be safe in both request and worker contexts.

## Key Concepts

- **Thin routes** — route handlers call helper/service functions and templates (`app/main.py:69`).
- **Search context helper** — normalizes blank strings and dates before search (`app/main.py:221`).
- **Slack service** — signature verification, event conversion, enrichment, and backfill (`app/services/slack.py:17`).
- **Ingestion service** — URL extraction, source lookup, dedupe, and mention insert (`app/services/ingestion.py:41`).
- **Metadata service** — retry/backoff and metadata application (`app/services/metadata.py:15`).

## Route Pattern

Web routes check `is_authenticated` and redirect or reject before querying data. JSON partial routes should return structured failures rather than HTML redirects when the caller expects JSON (`app/main.py:99`).

For new Zotero operator routes, keep the same shape:

```python
# app/main.py:168
@app.get("/status", response_class=HTMLResponse)
def status_page(request: Request, db: Session = Depends(get_db)):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
```

## Service Pattern

New service modules should expose small functions with explicit inputs. Avoid hidden global clients except cached settings. For external APIs, accept enough configuration to test behavior without real network calls.

For example, Slack has a small client wrapper and separate enrichment function (`app/services/slack.py:74`, `app/services/slack.py:140`). Zotero and Semantic Scholar should follow a similar pattern.

## Error Handling

At external boundaries, record failures and keep local source records. Metadata failures mark `metadata_status = "failed"` and set retry state (`app/services/metadata.py:54`). Slack enrichment treats names/permalinks as helpful but optional (`app/services/slack.py:149`).

Do not let a failed related-paper request block Zotero item sync. Do not let a failed Zotero note update delete local Slack provenance.

## Worker Pattern

The worker runs forever, refreshing metadata and catching up known channels (`app/worker.py:13`). It catches channel-level errors so one Slack failure does not stop the loop (`app/worker.py:20`).

Keep long-running worker additions bounded and observable. Log useful summaries, but never log secrets.

## Adding New Integrations

For Zotero or Semantic Scholar, add a small client wrapper plus service functions that accept explicit inputs and return domain-level results. Keep persistence decisions in sync services, not in low-level API clients.

New external clients should be easy to mock in tests. Avoid constructing clients deep inside pure parsing functions.

## Cross-References

- Related: [docs/api.md](./api.md)
- Related: [docs/database.md](./database.md)
- Related: [docs/testing.md](./testing.md)
