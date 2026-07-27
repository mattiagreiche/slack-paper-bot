from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import (
    SlackInstallation,
    TrialZoteroDestination,
    ZoteroCollectionSync,
    ZoteroItemSync,
    utcnow,
)
from app.services.credentials import CredentialCipher, CredentialEncryptionError


REQUIRED_SLACK_BOT_SCOPES = frozenset(
    {"channels:history", "channels:read", "users:read"}
)
DEFAULT_ZOTERO_API_BASE_URL = "https://api.zotero.org"
VALID_CREDENTIAL_STATUS = "valid"


@dataclass(frozen=True)
class SlackWorkspaceContext:
    team_id: str
    team_name: str
    bot_user_id: str
    granted_scopes: frozenset[str]
    bot_token: str = field(repr=False)
    app_id: str | None = None


@dataclass(frozen=True)
class ZoteroDestinationContext:
    group_id: str
    api_key: str = field(repr=False)
    group_name: str | None = None
    api_base_url: str = DEFAULT_ZOTERO_API_BASE_URL


@dataclass(frozen=True)
class ActivationResult:
    activated: bool
    reason: str


@dataclass(frozen=True)
class DestinationConfigurationResult:
    configured: bool
    reason: str


def get_current_installation(db: Session) -> SlackInstallation | None:
    return db.get(SlackInstallation, 1)


def get_active_workspace_context(
    db: Session,
    *,
    team_id: str,
    cipher: CredentialCipher,
) -> SlackWorkspaceContext | None:
    installation = get_current_installation(db)
    if (
        installation is None
        or not installation.is_active
        or installation.team_id != team_id
        or installation.credential_status != VALID_CREDENTIAL_STATUS
        or not _has_required_installation_state(installation)
        or get_verified_zotero_context(db, cipher=cipher) is None
    ):
        return None

    try:
        bot_token = cipher.decrypt(installation.encrypted_bot_token)
    except CredentialEncryptionError:
        return None

    return SlackWorkspaceContext(
        team_id=installation.team_id,
        team_name=installation.team_name,
        bot_user_id=installation.bot_user_id,
        granted_scopes=_parse_scopes(installation.granted_scopes),
        bot_token=bot_token,
        app_id=installation.app_id,
    )


def get_verified_zotero_context(
    db: Session,
    *,
    cipher: CredentialCipher,
) -> ZoteroDestinationContext | None:
    destination = db.get(TrialZoteroDestination, 1)
    if (
        destination is None
        or not destination.is_verified
        or destination.status != "verified"
        or not destination.group_id.strip()
        or not destination.api_base_url.strip()
        or not destination.encrypted_api_key
    ):
        return None

    try:
        api_key = cipher.decrypt(destination.encrypted_api_key)
    except CredentialEncryptionError:
        return None

    return ZoteroDestinationContext(
        group_id=destination.group_id,
        group_name=destination.group_name,
        api_base_url=destination.api_base_url,
        api_key=api_key,
    )


def activate_installation(
    db: Session,
    *,
    required_scopes: Iterable[str] = REQUIRED_SLACK_BOT_SCOPES,
    now: datetime | None = None,
) -> ActivationResult:
    validated_at = now or utcnow()
    installation = get_current_installation(db)
    if installation is None:
        return ActivationResult(False, "No Slack installation is configured")

    missing_identity = _missing_installation_identity(installation)
    if missing_identity:
        reason = f"Slack authorization is incomplete: {', '.join(missing_identity)}"
        _mark_inactive(
            installation,
            now=validated_at,
            status_code="authorization_incomplete",
            status_message=reason,
            credential_status="invalid",
            record_validation=True,
        )
        db.commit()
        return ActivationResult(False, reason)

    required = frozenset(scope.strip() for scope in required_scopes if scope.strip())
    missing_scopes = sorted(required - _parse_scopes(installation.granted_scopes))
    if missing_scopes:
        reason = f"Slack authorization is missing required scopes: {', '.join(missing_scopes)}"
        _mark_inactive(
            installation,
            now=validated_at,
            status_code="missing_required_scopes",
            status_message=reason,
            record_validation=True,
        )
        db.commit()
        return ActivationResult(False, reason)

    if installation.credential_status != VALID_CREDENTIAL_STATUS:
        reason = "Slack credential has not been validated"
        _mark_inactive(
            installation,
            now=validated_at,
            status_code="credential_not_valid",
            status_message=reason,
            record_validation=True,
        )
        db.commit()
        return ActivationResult(False, reason)

    destination = db.get(TrialZoteroDestination, 1)
    if (
        destination is None
        or not destination.is_verified
        or destination.status != "verified"
        or not destination.group_id.strip()
        or not destination.api_base_url.strip()
        or not destination.encrypted_api_key
    ):
        reason = "A verified Trial Zotero Destination is required"
        _mark_inactive(
            installation,
            now=validated_at,
            status_code="zotero_destination_required",
            status_message=reason,
            record_validation=True,
        )
        db.commit()
        return ActivationResult(False, reason)

    installation.is_active = True
    installation.status_code = "active"
    installation.status_message = "Slack installation is active"
    installation.last_validated_at = validated_at
    installation.deactivated_at = None
    db.commit()
    return ActivationResult(True, "Slack installation activated")


def deactivate_installation(
    db: Session,
    *,
    now: datetime | None = None,
) -> ActivationResult:
    installation = get_current_installation(db)
    if installation is None:
        return ActivationResult(False, "No Slack installation is configured")

    _mark_inactive(
        installation,
        now=now or utcnow(),
        status_code="manually_deactivated",
        status_message="Slack installation was manually deactivated",
        record_deactivation=True,
    )
    db.commit()
    return ActivationResult(False, "Slack installation deactivated")


def configure_trial_zotero_destination(
    db: Session,
    *,
    group_id: str,
    api_key: str,
    cipher: CredentialCipher,
    verification_succeeded: bool,
    verification_error: str | None,
    group_name: str | None = None,
    api_base_url: str = DEFAULT_ZOTERO_API_BASE_URL,
    now: datetime | None = None,
) -> DestinationConfigurationResult:
    destination = db.get(TrialZoteroDestination, 1)
    safe_error = _safe_reason(verification_error, secret=api_key)
    validated_at = now or utcnow()
    if not verification_succeeded:
        if destination is None or not _destination_is_verified(destination):
            destination = _record_failed_destination(
                db,
                destination=destination,
                group_id=group_id,
                group_name=group_name,
                api_base_url=api_base_url,
                api_key=api_key,
                cipher=cipher,
                status_message=safe_error or "Zotero access could not be verified",
                validated_at=validated_at,
            )
            if destination is not None:
                db.commit()
        return DestinationConfigurationResult(
            False,
            safe_error or "Zotero access could not be verified",
        )

    if not group_id.strip() or not api_key or not api_base_url.strip():
        return DestinationConfigurationResult(False, "Zotero destination is incomplete")

    normalized_group_id = group_id.strip()
    normalized_base_url = _normalized_api_base_url(api_base_url)
    destination_changed = destination is not None and (
        destination.group_id != normalized_group_id
        or destination.api_base_url != normalized_base_url
    )
    encrypted_api_key = cipher.encrypt(api_key)
    if destination is None:
        destination = TrialZoteroDestination(id=1)
        db.add(destination)

    if destination_changed:
        db.query(ZoteroItemSync).delete(synchronize_session=False)
        db.query(ZoteroCollectionSync).delete(synchronize_session=False)

    destination.group_id = normalized_group_id
    destination.group_name = _optional_text(group_name)
    destination.api_base_url = normalized_base_url
    destination.encrypted_api_key = encrypted_api_key
    destination.is_verified = True
    destination.status = "verified"
    destination.status_code = "access_verified"
    destination.status_message = "Zotero destination access is verified"
    destination.verified_at = validated_at
    destination.last_validated_at = validated_at
    db.commit()
    return DestinationConfigurationResult(True, "Trial Zotero Destination verified")


def _parse_scopes(value: str | None) -> frozenset[str]:
    return frozenset(scope.strip() for scope in (value or "").split(",") if scope.strip())


def _missing_installation_identity(installation: SlackInstallation) -> list[str]:
    return [
        name
        for name, value in (
            ("workspace identity", installation.team_id),
            ("bot identity", installation.bot_user_id),
            ("bot credential", installation.encrypted_bot_token),
        )
        if not value or not value.strip()
    ]


def _has_required_installation_state(installation: SlackInstallation) -> bool:
    return (
        not _missing_installation_identity(installation)
        and REQUIRED_SLACK_BOT_SCOPES.issubset(
            _parse_scopes(installation.granted_scopes)
        )
    )


def _mark_inactive(
    installation: SlackInstallation,
    *,
    now: datetime,
    status_code: str,
    status_message: str,
    credential_status: str | None = None,
    record_validation: bool = False,
    record_deactivation: bool = False,
) -> None:
    was_active = installation.is_active
    installation.is_active = False
    installation.status_code = status_code
    installation.status_message = status_message
    if record_validation:
        installation.last_validated_at = now
    if was_active or record_deactivation:
        installation.deactivated_at = now
    if credential_status is not None:
        installation.credential_status = credential_status


def _optional_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def _normalized_api_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def _destination_is_verified(destination: TrialZoteroDestination) -> bool:
    return destination.is_verified and destination.status == "verified"


def _record_failed_destination(
    db: Session,
    *,
    destination: TrialZoteroDestination | None,
    group_id: str,
    group_name: str | None,
    api_base_url: str,
    api_key: str,
    cipher: CredentialCipher,
    status_message: str,
    validated_at: datetime,
) -> TrialZoteroDestination | None:
    if not group_id.strip() or not api_key or not api_base_url.strip():
        return destination
    if destination is None:
        destination = TrialZoteroDestination(id=1)
        db.add(destination)
    destination.group_id = group_id.strip()
    destination.group_name = _optional_text(group_name)
    destination.api_base_url = _normalized_api_base_url(api_base_url)
    destination.encrypted_api_key = cipher.encrypt(api_key)
    destination.is_verified = False
    destination.status = "verification_failed"
    destination.status_code = "access_not_verified"
    destination.status_message = status_message
    destination.verified_at = None
    destination.last_validated_at = validated_at
    return destination


def _safe_reason(value: str | None, *, secret: str) -> str:
    reason = (value or "").replace(secret, "[redacted]") if secret else (value or "")
    return reason.strip()[:240]
