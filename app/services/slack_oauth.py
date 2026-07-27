from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import secrets
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import SlackInstallation, SlackOAuthAttempt, TrialZoteroDestination
from app.services.credentials import CredentialCipher, CredentialEncryptionError


SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
REQUIRED_SLACK_BOT_SCOPES = frozenset(
    {"channels:history", "channels:read", "users:read"}
)
DEFAULT_STATE_TTL = timedelta(minutes=10)
INSTALLATION_LOCK_KEY = 7_251_938_413


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    state: str = dataclass_field(repr=False)


@dataclass(frozen=True)
class OAuthCompletion:
    success: bool
    message: str
    team_id: str | None = None


class _UnsafeOAuthResponse(ValueError):
    pass


def begin_slack_oauth(
    db: Session,
    *,
    client_id: str,
    redirect_uri: str,
    replacement_approved: bool = False,
    now: datetime | None = None,
    state_ttl: timedelta = DEFAULT_STATE_TTL,
) -> OAuthStart:
    _lock_postgres_installation_slot(db)
    requested_at = _utc(now)
    state = secrets.token_urlsafe(32)
    installation = db.get(SlackInstallation, 1)
    expected_team_id = installation.team_id if installation is not None else None

    attempt = SlackOAuthAttempt(
        state_hash=_state_hash(state),
        purpose="replace" if replacement_approved else "install",
        expected_team_id=expected_team_id,
        replacement_approved=replacement_approved,
        status="pending",
        expires_at=requested_at + state_ttl,
        created_at=requested_at,
    )
    db.add(attempt)

    if installation is not None:
        installation.last_oauth_attempt_at = requested_at
    db.commit()

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(sorted(REQUIRED_SLACK_BOT_SCOPES)),
            "state": state,
        }
    )
    return OAuthStart(authorization_url=f"{SLACK_AUTHORIZE_URL}?{query}", state=state)


def complete_slack_oauth(
    db: Session,
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    redirect_uri: str,
    exchange_code: Callable[..., Mapping[str, Any] | Any],
    cipher: CredentialCipher,
    now: datetime | None = None,
) -> OAuthCompletion:
    completed_at = _utc(now)
    attempt = _find_attempt(db, state)
    if attempt is None:
        return OAuthCompletion(False, "Slack authorization state is invalid or already used")

    if attempt.claimed_at is not None:
        return OAuthCompletion(False, "Slack authorization state is invalid or already used")

    if _is_expired(attempt.expires_at, completed_at):
        _finish_attempt(
            db,
            attempt,
            status="expired",
            message="Authorization state expired",
            now=completed_at,
        )
        return OAuthCompletion(False, "Slack authorization state has expired")

    if not _claim_attempt(db, attempt, completed_at):
        return OAuthCompletion(False, "Slack authorization state is invalid or already used")

    if _attempt_is_stale(db, attempt):
        _finish_attempt(
            db,
            attempt,
            status="stale",
            message="A newer authorization attempt superseded this callback",
            now=completed_at,
        )
        return OAuthCompletion(False, "A newer Slack authorization attempt already exists")

    if error:
        _finish_attempt(
            db,
            attempt,
            status="denied",
            message="Slack authorization was denied",
            now=completed_at,
        )
        return OAuthCompletion(False, "Slack authorization was denied or cancelled")

    if not code:
        _finish_attempt(
            db,
            attempt,
            status="invalid_callback",
            message="Authorization code was missing",
            now=completed_at,
        )
        return OAuthCompletion(False, "Slack authorization could not be completed")

    try:
        raw_response = _resolve_exchange(
            exchange_code(code=code, redirect_uri=redirect_uri)
        )
        authorization = _parse_authorization(raw_response)
    except Exception:  # noqa: BLE001 - provider failures must remain credential-free.
        _finish_attempt(
            db,
            attempt,
            status="exchange_failed",
            message="Slack credential exchange failed",
            now=completed_at,
        )
        return OAuthCompletion(False, "Slack authorization could not be completed")

    current = _lock_installation_slot(db)
    if _attempt_is_stale(db, attempt):
        _finish_attempt(
            db,
            attempt,
            status="stale",
            message="A newer authorization attempt superseded this callback",
            now=completed_at,
            team_id=authorization.team_id,
        )
        return OAuthCompletion(False, "A newer Slack authorization has already completed")

    expected_team_id = attempt.expected_team_id
    if (
        expected_team_id
        and (current is None or current.team_id != expected_team_id)
    ):
        _finish_attempt(
            db,
            attempt,
            status="stale",
            message="The installed workspace changed during authorization",
            now=completed_at,
            team_id=authorization.team_id,
        )
        return OAuthCompletion(False, "The installed Slack workspace has changed")

    if (
        current is not None
        and current.team_id != authorization.team_id
        and not attempt.replacement_approved
    ):
        _finish_attempt(
            db,
            attempt,
            status="workspace_rejected",
            message="A different workspace requires operator-approved replacement",
            now=completed_at,
            team_id=authorization.team_id,
        )
        return OAuthCompletion(
            False,
            "A different Slack workspace cannot replace the current installation",
        )

    missing_scopes = REQUIRED_SLACK_BOT_SCOPES - authorization.scopes
    if missing_scopes:
        missing_scope_names = ", ".join(sorted(missing_scopes))
        invalid_scope_message = (
            f"Slack authorization is missing required permissions: {missing_scope_names}"
        )
        if current is not None and current.team_id == authorization.team_id:
            _mark_scope_invalid(
                current,
                now=completed_at,
                message=invalid_scope_message,
            )
        _finish_attempt(
            db,
            attempt,
            status="invalid_scopes",
            message=invalid_scope_message,
            now=completed_at,
            team_id=authorization.team_id,
            commit=False,
        )
        db.commit()
        return OAuthCompletion(False, invalid_scope_message)

    try:
        encrypted_bot_token = cipher.encrypt(authorization.bot_token)
    except CredentialEncryptionError:
        _finish_attempt(
            db,
            attempt,
            status="encryption_failed",
            message="Slack credential storage failed",
            now=completed_at,
            team_id=authorization.team_id,
        )
        return OAuthCompletion(False, "Slack authorization could not be stored")

    destination_verified = _verified_zotero_destination_exists(db)
    preserve_active = _should_preserve_active_installation(
        current=current,
        authorization=authorization,
        attempt=attempt,
        destination_verified=destination_verified,
    )
    was_active = current.is_active if current is not None else False
    if current is None:
        current = SlackInstallation(
            **_installation_values(
                authorization,
                encrypted_bot_token=encrypted_bot_token,
                now=completed_at,
            )
        )
        db.add(current)
    else:
        for name, value in _installation_values(
            authorization,
            encrypted_bot_token=encrypted_bot_token,
            now=completed_at,
        ).items():
            setattr(current, name, value)

    current.is_active = preserve_active
    current.credential_status = "valid"
    if preserve_active:
        current.status_code = "active"
        current.status_message = "Slack installation is active"
        current.deactivated_at = None
    elif not destination_verified:
        current.status_code = "zotero_destination_required"
        current.status_message = "A verified Trial Zotero Destination is required"
    else:
        current.status_code = "awaiting_activation"
        current.status_message = "Slack authorization is awaiting operator activation"
    if was_active and not preserve_active:
        current.deactivated_at = completed_at
    _finish_attempt(
        db,
        attempt,
        status="succeeded",
        message="Slack authorization completed",
        now=completed_at,
        team_id=authorization.team_id,
        commit=False,
    )
    attempt_id = attempt.id
    try:
        db.commit()
    except IntegrityError:
        return _handle_singleton_integrity_error(
            db,
            attempt_id=attempt_id,
            authorization=authorization,
            encrypted_bot_token=encrypted_bot_token,
            now=completed_at,
        )
    message = (
        "Slack workspace reauthorized and remains active"
        if preserve_active
        else "Slack workspace authorized and awaiting operator activation"
    )
    return OAuthCompletion(True, message, authorization.team_id)


@dataclass(frozen=True)
class _Authorization:
    team_id: str
    team_name: str
    app_id: str
    bot_user_id: str
    bot_token: str = dataclass_field(repr=False)
    scopes: frozenset[str]
    granted_scopes: str


def _parse_authorization(response: Mapping[str, Any]) -> _Authorization:
    if not isinstance(response, Mapping) or response.get("ok") is not True:
        raise _UnsafeOAuthResponse

    team = response.get("team")
    if not isinstance(team, Mapping):
        raise _UnsafeOAuthResponse

    scopes = _normalized_scopes(response.get("scope"))
    values = {
        "team_id": team.get("id"),
        "team_name": team.get("name"),
        "bot_user_id": response.get("bot_user_id"),
        "bot_token": response.get("access_token"),
    }
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise _UnsafeOAuthResponse
    app_id = response.get("app_id")
    if not isinstance(app_id, str) or not app_id.strip():
        raise _UnsafeOAuthResponse

    return _Authorization(
        team_id=values["team_id"].strip(),
        team_name=values["team_name"].strip(),
        app_id=app_id.strip(),
        bot_user_id=values["bot_user_id"].strip(),
        bot_token=values["bot_token"],
        scopes=scopes,
        granted_scopes=",".join(sorted(scopes)),
    )


def _installation_values(
    authorization: _Authorization,
    *,
    encrypted_bot_token: str,
    now: datetime,
) -> dict[str, Any]:
    return {
        "id": 1,
        "app_id": authorization.app_id,
        "team_id": authorization.team_id,
        "team_name": authorization.team_name,
        "bot_user_id": authorization.bot_user_id,
        "encrypted_bot_token": encrypted_bot_token,
        "granted_scopes": authorization.granted_scopes,
        "credential_status": "valid",
        "is_active": False,
        "status_code": "awaiting_activation",
        "status_message": "Slack authorization is awaiting operator activation",
        "installed_at": now,
        "updated_at": now,
        "last_oauth_attempt_at": now,
    }


def _lock_postgres_installation_slot(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(INSTALLATION_LOCK_KEY)))


def _lock_installation_slot(db: Session) -> SlackInstallation | None:
    _lock_postgres_installation_slot(db)
    return db.execute(
        select(SlackInstallation)
        .where(SlackInstallation.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def _should_preserve_active_installation(
    *,
    current: SlackInstallation | None,
    authorization: _Authorization,
    attempt: SlackOAuthAttempt,
    destination_verified: bool,
) -> bool:
    return (
        current is not None
        and current.team_id == authorization.team_id
        and current.is_active
        and not attempt.replacement_approved
        and REQUIRED_SLACK_BOT_SCOPES.issubset(authorization.scopes)
        and destination_verified
    )


def _verified_zotero_destination_exists(db: Session) -> bool:
    destination = db.execute(
        select(TrialZoteroDestination)
        .where(TrialZoteroDestination.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    return bool(
        destination is not None
        and destination.is_verified
        and destination.status == "verified"
        and destination.group_id.strip()
        and destination.api_base_url.strip()
        and destination.encrypted_api_key
    )


def _mark_scope_invalid(
    installation: SlackInstallation,
    *,
    now: datetime,
    message: str,
) -> None:
    was_active = installation.is_active
    installation.is_active = False
    installation.status_code = "invalid_oauth_scopes"
    installation.status_message = message
    installation.last_oauth_attempt_at = now
    if was_active:
        installation.deactivated_at = now


def _handle_singleton_integrity_error(
    db: Session,
    *,
    attempt_id: str,
    authorization: _Authorization,
    encrypted_bot_token: str,
    now: datetime,
) -> OAuthCompletion:
    db.rollback()
    attempt = db.get(SlackOAuthAttempt, attempt_id)
    if attempt is None:
        return OAuthCompletion(False, "Slack authorization could not be stored")

    current = _lock_installation_slot(db)
    winning_attempt = (
        db.query(SlackOAuthAttempt)
        .filter(
            SlackOAuthAttempt.id != attempt.id,
            SlackOAuthAttempt.status == "succeeded",
        )
        .order_by(SlackOAuthAttempt.created_at.desc())
        .first()
    )
    if (
        current is not None
        and winning_attempt is not None
        and _as_aware(attempt.created_at) > _as_aware(winning_attempt.created_at)
        and current.team_id == authorization.team_id
        and not _attempt_is_stale(db, attempt)
    ):
        for name, value in _installation_values(
            authorization,
            encrypted_bot_token=encrypted_bot_token,
            now=now,
        ).items():
            setattr(current, name, value)
        current.is_active = False
        current.status_code = "awaiting_activation"
        current.status_message = "Slack authorization is awaiting operator activation"
        _finish_attempt(
            db,
            attempt,
            status="succeeded",
            message="Slack authorization completed",
            now=now,
            team_id=authorization.team_id,
            commit=False,
        )
        db.commit()
        return OAuthCompletion(
            True,
            "Slack workspace authorized and awaiting operator activation",
            authorization.team_id,
        )

    status = "stale" if _attempt_is_stale(db, attempt) else "concurrent_install"
    _finish_attempt(
        db,
        attempt,
        status=status,
        message="A concurrent Slack installation already completed",
        now=now,
        team_id=authorization.team_id,
    )
    return OAuthCompletion(False, "A concurrent Slack authorization already completed")


def _find_attempt(db: Session, state: str | None) -> SlackOAuthAttempt | None:
    if not isinstance(state, str) or not state:
        return None
    return (
        db.query(SlackOAuthAttempt)
        .filter(SlackOAuthAttempt.state_hash == _state_hash(state))
        .one_or_none()
    )


def _claim_attempt(db: Session, attempt: SlackOAuthAttempt, now: datetime) -> bool:
    claimed = (
        db.query(SlackOAuthAttempt)
        .filter(
            SlackOAuthAttempt.id == attempt.id,
            SlackOAuthAttempt.claimed_at.is_(None),
            SlackOAuthAttempt.expires_at > now,
        )
        .update(
            {
                SlackOAuthAttempt.claimed_at: now,
                SlackOAuthAttempt.status: "claimed",
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if not claimed:
        return False
    db.refresh(attempt)
    return True


def _finish_attempt(
    db: Session,
    attempt: SlackOAuthAttempt,
    *,
    status: str,
    message: str,
    now: datetime,
    team_id: str | None = None,
    commit: bool = True,
) -> None:
    attempt.status = status
    attempt.result_code = status
    attempt.result_message = message
    attempt.result_team_id = team_id
    attempt.consumed_at = now
    attempt.completed_at = now
    if commit:
        db.commit()


def _attempt_is_stale(
    db: Session,
    attempt: SlackOAuthAttempt,
) -> bool:
    attempt_created_at = attempt.created_at

    return (
        db.query(SlackOAuthAttempt.id)
        .filter(
            SlackOAuthAttempt.id != attempt.id,
            SlackOAuthAttempt.created_at > attempt_created_at,
        )
        .first()
        is not None
    )


def _resolve_exchange(value: Any) -> Mapping[str, Any]:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, value).result()


def _normalized_scopes(value: Any) -> frozenset[str]:
    if not isinstance(value, str):
        return frozenset()
    return frozenset(scope.strip() for scope in value.split(",") if scope.strip())


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return _as_aware(value)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expired(expires_at: datetime, now: datetime) -> bool:
    return _as_aware(expires_at) <= _as_aware(now)
