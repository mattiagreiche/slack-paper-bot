from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SlackInstallation
from app.services.credentials import CredentialCipher, CredentialEncryptionError
from app.services.installations import SlackWorkspaceContext, get_active_workspace_context


def resolve_workspace_context(
    db: Session,
    *,
    team_id: str,
    settings: Settings,
    cipher: CredentialCipher | None,
) -> SlackWorkspaceContext | None:
    """Resolve OAuth credentials, or the temporary exact-team migration bridge."""
    if db.get(SlackInstallation, 1) is not None:
        if cipher is None:
            return None
        return get_active_workspace_context(db, team_id=team_id, cipher=cipher)

    if (
        not settings.slack_oauth_migration_mode
        or not settings.slack_legacy_team_id
        or settings.slack_legacy_team_id != team_id
        or not settings.slack_bot_token
    ):
        return None

    return SlackWorkspaceContext(
        team_id=team_id,
        team_name=team_id,
        bot_user_id="legacy",
        granted_scopes=frozenset({"channels:history", "channels:read", "users:read"}),
        bot_token=settings.slack_bot_token,
    )


def resolve_configured_workspace_context(
    db: Session,
    *,
    settings: Settings,
) -> SlackWorkspaceContext | None:
    installation = db.get(SlackInstallation, 1)
    team_id = installation.team_id if installation else settings.slack_legacy_team_id
    if not team_id:
        return None
    try:
        cipher = CredentialCipher(settings.credential_encryption_key)
    except CredentialEncryptionError:
        cipher = None
    return resolve_workspace_context(
        db,
        team_id=team_id,
        settings=settings,
        cipher=cipher,
    )
