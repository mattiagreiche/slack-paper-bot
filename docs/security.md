# Security

> **AI Context Summary**: Security hinges on Slack signature verification, shared-password web access, secret hygiene, and trial privacy boundaries. The app should never expose credentials or full Slack message text. Zotero sync must not overwrite human-authored library content.

## Overview

The project is a demo/trial tool, but it still touches Slack workspace data and a shared Zotero library. Treat every external request and token as a trust boundary.

## Key Concepts

- **Slack HMAC validation** — required for `/slack/events` (`app/services/slack.py:17`).
- **Shared password auth** — protects local web pages (`app/auth.py:19`).
- **No message text storage** — ingestion stores URLs and provenance, not full Slack messages (`app/models.py:86`).
- **Credential env vars** — settings read secrets from `.env` (`app/config.py:7`).
- **Encrypted stored credentials** — Slack and Zotero credentials use one stable
  `CREDENTIAL_ENCRYPTION_KEY`; plaintext credentials must not be persisted.

## Slack Boundaries

The trial monitors only opted-in public channels. Do not process direct messages. Private channels are excluded from the Zotero trial even though older code paths can represent private channel metadata.

Slack enrichment failures should not crash ingestion, but they also should not bypass signature verification.

`/slack/oauth/callback` and `/slack/events` are separate trust boundaries. The
callback validates one-time OAuth state before exchanging a code. The events
endpoint validates Slack's timestamped HMAC signature. Never accept an OAuth
callback as an event or use the shared-password cookie in place of either check.

## Zotero Boundaries

The bot owns its own notes/tags/collections. It must not overwrite human-authored notes, non-bot tags, collection choices, or item metadata unless the field is explicitly bot-owned by the spec.

External related papers are suggestions only and must not be auto-imported.

The verified Trial Zotero Destination stored by the authenticated `/status`
flow is the sole production source for the group ID and encrypted API key.
Do not duplicate those credentials in deployment environment variables.

## Secrets

Never expose:

- `APP_SECRET_KEY`
- `SHARED_PASSWORD`
- `SLACK_SIGNING_SECRET`
- `SLACK_CLIENT_SECRET`
- `CREDENTIAL_ENCRYPTION_KEY`
- stored or temporary `SLACK_BOT_TOKEN` values
- Zotero API credentials

Avoid logging raw external API payloads if they may contain tokens, private URLs, or workspace-sensitive content.

The API may receive Slack OAuth client credentials, the signing secret, and the
encryption key. The worker receives only the encryption key plus any temporary
legacy bridge inputs; it must not receive the OAuth client secret, redirect URI,
or Slack signing secret. Keep `.env` mode `0600`, out of build contexts and
image layers, and outside container source mounts. The Dockerfile copies only
explicit runtime source paths and `.dockerignore` excludes local secrets.

`SLACK_BOT_TOKEN`, `SLACK_OAUTH_MIGRATION_MODE`, and `SLACK_LEGACY_TEAM_ID` are
a temporary, fail-closed migration set. Use them only for the known test
workspace and delete them after OAuth event and worker smoke verification.
Changing or losing `CREDENTIAL_ENCRYPTION_KEY` makes stored credentials
unreadable; rotate it only through an intentional credential reset and
reauthorization.

## Data Minimization

Slack provenance should include channel, sharer, timestamp, original URL, and permalink when available. Do not store or sync full message excerpts during the trial.

Unsupported links may be visible in the local surface, but they should not create Zotero items unless they resolve to stable scholarly identifiers.

## Failure Disclosure

Operator-facing errors should identify the failed operation and provider. User-facing Zotero notes should stay human-useful; for example, external related papers can say unavailable without exposing stack traces or retry metadata.

Security-sensitive failures should be logged conservatively. Do not include request signatures, token strings, or raw authorization headers in errors.

## Review Checklist

Before shipping security-adjacent changes, check: auth boundary preserved, no new secret exposure, no full Slack text storage, no private-channel trial leakage, and no human Zotero content overwritten.

## Cross-References

- Related: [docs/authentication.md](./authentication.md)
- Related: [docs/deployment.md](./deployment.md)
- Related: [docs/api.md](./api.md)
