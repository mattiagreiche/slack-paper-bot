# Authentication

> **AI Context Summary**: Local web and operator access uses a shared-password cookie. Slack OAuth callbacks use one-time state, while Slack Events use request-signature verification. These are separate trust boundaries.

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

This gate protects search, details, BibTeX, status, Slack activation/replacement,
Zotero destination configuration, and retry routes.

## Slack OAuth Auth

`/slack/install` creates expiring random state whose hash is stored locally.
`/slack/oauth/callback` must claim that state exactly once before exchanging an
authorization code. A successful callback stores the bot credential encrypted
and leaves a new workspace inactive until operator activation.

## Slack Request Auth

Slack requests must include `X-Slack-Request-Timestamp` and `X-Slack-Signature`. `verify_slack_signature` rejects missing headers, stale timestamps, and invalid HMACs (`app/services/slack.py:24`).

Do not skip this check for local tunnel testing. Configure `SLACK_SIGNING_SECRET` instead.

## Secrets

Important secrets are `APP_SECRET_KEY`, `SHARED_PASSWORD`,
`SLACK_SIGNING_SECRET`, `SLACK_CLIENT_SECRET`,
`CREDENTIAL_ENCRYPTION_KEY`, stored Slack bot credentials, and stored Zotero API
credentials.

Never print credentials in logs, status pages, tests, exceptions, or Zotero notes.

## Trial Privacy Boundaries

The Zotero trial excludes private Slack channels. Do not build logic that makes private channel provenance visible through Zotero or the local surface unless the spec is explicitly changed.

## Session Behavior

The cookie value is deterministic for a given `APP_SECRET_KEY` and `SHARED_PASSWORD`. Changing either invalidates existing sessions, which is acceptable for the trial.

The cookie is HTTP-only and same-site lax (`app/main.py:58`). A persistent HTTPS
deployment must add secure-cookie handling together with trusted reverse-proxy
configuration rather than exposing the development server directly.

## Testing Auth

Route tests should authenticate through the same cookie behavior rather than bypassing route checks. Slack webhook tests should provide signed requests or target the signature helper directly.

Do not add shortcuts that disable auth based on environment names. Test helpers are safer than production conditionals.

## Future Access Model

If the lab trial outgrows a shared password, add a new access model deliberately. Do not mix partial user identity into the current cookie scheme without a spec update.

## Cross-References

- Related: [docs/api.md](./api.md)
- Related: [docs/deployment.md](./deployment.md)
- Related: [docs/security.md](./security.md)
