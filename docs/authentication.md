# Authentication

> **AI Context Summary**: Local web access uses a shared-password cookie; Slack webhooks use Slack signature verification. These are separate trust boundaries. Future Zotero operator controls should use the local shared-password gate unless the access model changes.

## Overview

The MVP uses a shared lab password for local pages. This is intentionally simple for the trial and should not be treated as lab-wide identity management.

Slack Events are authenticated by Slack request signatures. A valid shared web password does not authorize Slack webhook calls, and a Slack token does not authorize local web pages.

## Key Concepts

- **Cookie name** — `paper_archive_auth` (`app/auth.py:7`).
- **Auth token** — HMAC of shared password using app secret (`app/auth.py:10`).
- **Cookie check** — constant-time comparison in `is_authenticated` (`app/auth.py:19`).
- **Slack signature check** — timestamp and HMAC validation (`app/services/slack.py:17`).
- **Tolerance window** — default 5 minutes (`app/config.py:16`).

## Local Web Auth

Login reads form data, compares to `Settings.shared_password`, and sets an HTTP-only same-site cookie (`app/main.py:46`). Logout deletes the cookie (`app/main.py:62`).

This gate protects search, details, BibTeX, and status pages. Future operator routes for Zotero sync should use the same gate unless the spec changes.

## Slack Request Auth

Slack requests must include `X-Slack-Request-Timestamp` and `X-Slack-Signature`. `verify_slack_signature` rejects missing headers, stale timestamps, and invalid HMACs (`app/services/slack.py:24`).

Do not skip this check for local tunnel testing. Configure `SLACK_SIGNING_SECRET` instead.

## Secrets

Important secrets are `APP_SECRET_KEY`, `SHARED_PASSWORD`, `SLACK_SIGNING_SECRET`, and `SLACK_BOT_TOKEN`. Future Zotero credentials should be treated the same way.

Never print credentials in logs, status pages, tests, exceptions, or Zotero notes.

## Trial Privacy Boundaries

The Zotero trial excludes private Slack channels. Do not build logic that makes private channel provenance visible through Zotero or the local surface unless the spec is explicitly changed.

## Session Behavior

The cookie value is deterministic for a given `APP_SECRET_KEY` and `SHARED_PASSWORD`. Changing either invalidates existing sessions, which is acceptable for the trial.

The cookie is HTTP-only and same-site lax (`app/main.py:58`). If deployment moves behind HTTPS, keep cookie handling compatible with the reverse proxy and consider secure cookies when the environment is stable.

## Testing Auth

Route tests should authenticate through the same cookie behavior rather than bypassing route checks. Slack webhook tests should provide signed requests or target the signature helper directly.

Do not add shortcuts that disable auth based on environment names. Test helpers are safer than production conditionals.

## Future Access Model

If the lab trial outgrows a shared password, add a new access model deliberately. Do not mix partial user identity into the current cookie scheme without a spec update.

## Cross-References

- Related: [docs/api.md](./api.md)
- Related: [docs/deployment.md](./deployment.md)
- Related: [docs/security.md](./security.md)
