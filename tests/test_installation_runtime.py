import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import pytest

from app.auth import auth_token
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import (
    IngestionEvent,
    Paper,
    SlackChannel,
    SlackInstallation,
    SlackOAuthAttempt,
    SlackUser,
    TrialZoteroDestination,
)
from app.services.credentials import CredentialCipher
from app.services.installations import (
    SlackWorkspaceContext,
    configure_trial_zotero_destination,
)
from app.services.zotero import ZoteroDestinationVerification


REQUIRED_SCOPES = "channels:history,channels:read,users:read"
ENCRYPTION_KEY = base64.urlsafe_b64encode(b"r" * 32).decode()
SLACK_TOKEN = "xoxb-runtime"


@pytest.fixture()
def client(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_client_id", "client-id")
    monkeypatch.setattr(settings, "slack_client_secret", "client-secret")
    monkeypatch.setattr(
        settings,
        "slack_oauth_redirect_uri",
        "https://archive.example/slack/oauth/callback",
    )
    monkeypatch.setattr(settings, "credential_encryption_key", ENCRYPTION_KEY)

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


def _auth_cookie():
    return {"paper_archive_auth": auth_token()}


def _installation(db_session, *, team_id="T-ACTIVE", active=False):
    installation = SlackInstallation(
        id=1,
        team_id=team_id,
        team_name="Research Workspace",
        encrypted_bot_token=CredentialCipher(ENCRYPTION_KEY).encrypt(SLACK_TOKEN),
        bot_user_id="U-BOT",
        granted_scopes=REQUIRED_SCOPES,
        credential_status="valid",
        is_active=active,
    )
    db_session.add(installation)
    db_session.commit()
    return installation


def _destination(db_session, *, group_id="123456", api_key="zotero-secret"):
    result = configure_trial_zotero_destination(
        db_session,
        group_id=group_id,
        api_key=api_key,
        cipher=CredentialCipher(ENCRYPTION_KEY),
        verification_succeeded=True,
        verification_error=None,
    )
    assert result.configured


def _signed_event(
    team_id,
    *,
    event_id=None,
    event_type="message",
    text="https://arxiv.org/abs/1706.03762",
):
    settings = get_settings()
    event = {"type": event_type}
    if event_type == "message":
        event.update(
            {
                "channel_type": "channel",
                "channel": "C1",
                "user": "U1",
                "ts": "1784822400.000100",
                "text": text,
            }
        )
    payload = {
        "type": "event_callback",
        "team_id": team_id,
        "event_id": event_id or f"Ev-{team_id}",
        "event": event,
    }
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    signature = "v0=" + hmac.new(
        settings.slack_signing_secret.encode(),
        b"v0:" + timestamp.encode() + b":" + body,
        hashlib.sha256,
    ).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
    }


def test_install_route_redirects_to_slack_with_state(client):
    response = client.get("/slack/install", follow_redirects=False)

    assert response.status_code == 303
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://archive.example/slack/oauth/callback"]
    assert "state" in query


def test_oauth_callback_invalid_state_is_human_safe_and_does_not_expose_credentials(client):
    response = client.get(
        "/slack/oauth/callback",
        params={"error": "access_denied", "state": "returned-state"},
    )

    assert response.status_code == 400
    assert "state" in response.text.lower()
    assert "xoxb-" not in response.text
    assert "client-secret" not in response.text


def test_activation_requires_persisted_zotero_destination(client, db_session):
    installation = _installation(db_session)

    response = client.post(
        "/operator/slack/activate",
        cookies=_auth_cookie(),
        follow_redirects=False,
    )

    db_session.refresh(installation)
    assert response.status_code == 409
    assert installation.is_active is False


def test_operator_can_verify_one_destination_then_activate_and_deactivate(
    client,
    db_session,
    monkeypatch,
):
    installation = _installation(db_session)

    async def verify(**kwargs):
        assert kwargs["api_key"] in {"zotero-secret", "zotero-rotated"}
        return ZoteroDestinationVerification(
            verified=True,
            group_name="Research Library",
        )

    monkeypatch.setattr("app.main.verify_zotero_destination", verify)
    destination_response = client.post(
        "/operator/zotero-destination",
        data={"group_id": "123456", "api_key": "zotero-secret"},
        cookies=_auth_cookie(),
        follow_redirects=False,
    )
    update_response = client.post(
        "/operator/zotero-destination",
        data={"group_id": "654321", "api_key": "zotero-rotated"},
        cookies=_auth_cookie(),
        follow_redirects=False,
    )
    activate_response = client.post(
        "/operator/slack/activate",
        cookies=_auth_cookie(),
        follow_redirects=False,
    )
    db_session.refresh(installation)

    destination = db_session.query(TrialZoteroDestination).one()
    assert destination_response.status_code == 303
    assert update_response.status_code == 303
    assert destination.group_id == "654321"
    assert destination.encrypted_api_key != "zotero-rotated"
    assert CredentialCipher(ENCRYPTION_KEY).decrypt(destination.encrypted_api_key) == (
        "zotero-rotated"
    )
    assert installation.is_active is True

    deactivate_response = client.post(
        "/operator/slack/deactivate",
        cookies=_auth_cookie(),
        follow_redirects=False,
    )
    db_session.refresh(installation)
    assert activate_response.status_code == 303
    assert deactivate_response.status_code == 303
    assert installation.is_active is False


def test_replacement_start_is_operator_only_and_marks_oauth_attempt(client, db_session):
    _installation(db_session)

    unauthenticated = client.post("/operator/slack/replace/start", follow_redirects=False)
    approved = client.post(
        "/operator/slack/replace/start",
        cookies=_auth_cookie(),
        follow_redirects=False,
    )

    assert unauthenticated.status_code == 303
    assert unauthenticated.headers["location"] == "/login"
    assert approved.status_code == 303
    attempt = db_session.query(SlackOAuthAttempt).one()
    assert attempt.replacement_approved is True


@pytest.mark.parametrize(
    ("installed_team", "reason_code"),
    [(None, "unknown_workspace"), ("T-INACTIVE", "installation_inactive")],
)
def test_unknown_or_inactive_workspace_event_does_not_create_client_or_ingest(
    client,
    db_session,
    monkeypatch,
    installed_team,
    reason_code,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_signing_secret", "signing-secret")
    if installed_team is not None:
        _installation(db_session, team_id=installed_team, active=False)
    monkeypatch.setattr(
        "app.main.SlackApiClient",
        lambda token: pytest.fail("inactive events must not construct a Slack client"),
    )
    body, headers = _signed_event("T-INACTIVE")

    response = client.post("/slack/events", content=body, headers=headers)

    assert response.status_code == 200
    assert db_session.query(Paper).count() == 0
    diagnostic = db_session.query(IngestionEvent).one()
    assert diagnostic.error == reason_code
    assert diagnostic.key.startswith("T-INACTIVE:runtime:")


def test_event_for_team_other_than_exact_active_installation_does_not_ingest(
    client,
    db_session,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_signing_secret", "signing-secret")
    _installation(db_session, team_id="T-ACTIVE", active=True)
    _destination(db_session)
    body, headers = _signed_event("T-REPLACED")

    response = client.post("/slack/events", content=body, headers=headers)

    assert response.status_code == 200
    assert db_session.query(Paper).count() == 0


@pytest.mark.parametrize(
    ("active", "event_type"),
    [(False, "app_uninstalled"), (True, "tokens_revoked")],
)
def test_exact_current_team_revocation_invalidates_before_runtime_eligibility(
    client,
    db_session,
    monkeypatch,
    active,
    event_type,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_signing_secret", "signing-secret")
    installation = _installation(db_session, active=active)
    body, headers = _signed_event(
        "T-ACTIVE",
        event_id=f"Ev-{event_type}",
        event_type=event_type,
    )

    response = client.post("/slack/events", content=body, headers=headers)

    db_session.refresh(installation)
    diagnostic = db_session.query(IngestionEvent).one()
    assert response.status_code == 200
    assert installation.is_active is False
    assert installation.credential_status == "invalid"
    assert diagnostic.status == "revoked"
    assert diagnostic.error == "slack_credential_revoked"


def test_unknown_team_revocation_is_ignored_without_invalidating_current_installation(
    client,
    db_session,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_signing_secret", "signing-secret")
    installation = _installation(db_session, active=False)
    body, headers = _signed_event(
        "T-UNKNOWN",
        event_id="Ev-unknown-revocation",
        event_type="app_uninstalled",
    )

    response = client.post("/slack/events", content=body, headers=headers)

    db_session.refresh(installation)
    diagnostic = db_session.query(IngestionEvent).one()
    assert response.status_code == 200
    assert installation.credential_status == "valid"
    assert diagnostic.status == "ignored"
    assert diagnostic.error == "unknown_workspace"
    assert diagnostic.key.startswith("T-UNKNOWN:runtime:")


def test_active_workspace_event_uses_encrypted_context_and_namespaced_key(
    client,
    db_session,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_signing_secret", "signing-secret")
    _installation(db_session, active=True)
    _destination(db_session)

    class FakeClient:
        def __init__(self, token):
            assert token == SLACK_TOKEN

        async def conversation_info(self, channel_id):
            return {
                "id": channel_id,
                "name": "papers",
                "is_private": False,
                "is_member": True,
            }

        async def user_info(self, user_id):
            return {"id": user_id, "name": "Ada", "profile": {}}

        async def permalink(self, channel_id, message_ts):
            return f"https://slack.example/{channel_id}/{message_ts}"

    monkeypatch.setattr("app.main.SlackApiClient", FakeClient)
    body, headers = _signed_event("T-ACTIVE", event_id="Ev-active")

    response = client.post("/slack/events", content=body, headers=headers)

    assert response.status_code == 200
    assert db_session.query(Paper).count() == 1
    assert db_session.get(IngestionEvent, "T-ACTIVE:Ev-active") is not None


def test_active_event_identity_collision_is_ignored_with_safe_diagnostic(
    client,
    db_session,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_signing_secret", "signing-secret")
    _installation(db_session, active=True)
    _destination(db_session)
    db_session.add(
        SlackChannel(
            id="C1",
            team_id="T-OLD",
            name="historical-channel",
            is_private=False,
        )
    )
    db_session.add(
        SlackUser(
            id="U1",
            team_id="T-OLD",
            display_name="Historical User",
            real_name="Historical User",
        )
    )
    db_session.commit()

    class FakeClient:
        def __init__(self, token):
            assert token == SLACK_TOKEN

        async def conversation_info(self, channel_id):
            return {
                "id": channel_id,
                "name": "new-channel",
                "is_private": False,
                "is_member": True,
            }

        async def user_info(self, user_id):
            return {"id": user_id, "name": "New User", "profile": {}}

        async def permalink(self, channel_id, message_ts):
            return None

    monkeypatch.setattr("app.main.SlackApiClient", FakeClient)
    body, headers = _signed_event("T-ACTIVE", event_id="Ev-collision")

    response = client.post("/slack/events", content=body, headers=headers)

    diagnostic = db_session.query(IngestionEvent).one()
    assert response.status_code == 200
    assert diagnostic.error == "slack_identity_collision"
    assert db_session.get(SlackChannel, "C1").team_id == "T-OLD"
    assert db_session.get(SlackUser, "U1").team_id == "T-OLD"
    assert db_session.query(Paper).count() == 0


def test_invalid_current_credential_deactivates_installation(
    client,
    db_session,
    monkeypatch,
):
    from app.services.slack import SlackApiError

    settings = get_settings()
    monkeypatch.setattr(settings, "slack_signing_secret", "signing-secret")
    installation = _installation(db_session, active=True)
    _destination(db_session)

    class InvalidClient:
        def __init__(self, token):
            assert token == SLACK_TOKEN

        async def conversation_info(self, channel_id):
            raise SlackApiError("conversations.info", "invalid_auth")

    monkeypatch.setattr("app.main.SlackApiClient", InvalidClient)
    body, headers = _signed_event("T-ACTIVE", event_id="Ev-revoked")

    response = client.post("/slack/events", content=body, headers=headers)

    db_session.refresh(installation)
    assert response.status_code == 200
    assert installation.is_active is False
    assert installation.credential_status == "invalid"
    assert "xoxb" not in installation.status_message
    assert db_session.query(Paper).count() == 0


def test_legacy_adapter_never_falls_back_after_oauth_exists(db_session, monkeypatch):
    from app.services.legacy_slack import resolve_workspace_context

    settings = get_settings()
    monkeypatch.setattr(settings, "slack_oauth_migration_mode", True)
    monkeypatch.setattr(settings, "slack_legacy_team_id", "T-LEGACY")
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-legacy")
    _installation(db_session, team_id="T-OAUTH", active=False)

    assert resolve_workspace_context(
        db_session,
        team_id="T-LEGACY",
        settings=settings,
        cipher=CredentialCipher(ENCRYPTION_KEY),
    ) is None


def test_legacy_adapter_requires_mode_and_exact_team(db_session, monkeypatch):
    from app.services.legacy_slack import resolve_workspace_context

    settings = get_settings()
    monkeypatch.setattr(settings, "slack_legacy_team_id", "T-LEGACY")
    monkeypatch.setattr(settings, "slack_bot_token", "xoxb-legacy")
    monkeypatch.setattr(settings, "slack_oauth_migration_mode", False)
    assert resolve_workspace_context(
        db_session,
        team_id="T-LEGACY",
        settings=settings,
        cipher=None,
    ) is None

    monkeypatch.setattr(settings, "slack_oauth_migration_mode", True)
    assert resolve_workspace_context(
        db_session,
        team_id="T-OTHER",
        settings=settings,
        cipher=None,
    ) is None
    workspace = resolve_workspace_context(
        db_session,
        team_id="T-LEGACY",
        settings=settings,
        cipher=None,
    )
    assert workspace is not None
    assert workspace.bot_token == "xoxb-legacy"


def test_status_renders_only_safe_installation_and_destination_fields(
    client,
    db_session,
):
    installation = _installation(db_session)
    _destination(db_session)

    response = client.get("/status", cookies=_auth_cookie())

    assert response.status_code == 200
    assert installation.team_name in response.text
    assert "123456" in response.text
    assert SLACK_TOKEN not in response.text
    assert installation.encrypted_bot_token not in response.text
    destination = db_session.query(TrialZoteroDestination).one()
    assert "zotero-secret" not in response.text
    assert destination.encrypted_api_key not in response.text


def test_status_displays_safe_runtime_team_and_reason_without_event_body(
    client,
    db_session,
    monkeypatch,
):
    settings = get_settings()
    monkeypatch.setattr(settings, "slack_signing_secret", "signing-secret")
    body, headers = _signed_event(
        "T-UNKNOWN",
        event_id="Ev-safe-diagnostic",
        text="body-secret-must-not-persist",
    )
    client.post("/slack/events", content=body, headers=headers)

    response = client.get("/status", cookies=_auth_cookie())
    diagnostic = db_session.query(IngestionEvent).one()

    assert response.status_code == 200
    assert "T-UNKNOWN" in response.text
    assert "unknown_workspace" in response.text
    assert "body-secret-must-not-persist" not in response.text
    assert "body-secret-must-not-persist" not in repr(diagnostic)


def test_catch_up_refuses_channel_from_team_other_than_active_installation(db_session):
    from app.worker import _catch_up_channel

    workspace = SlackWorkspaceContext(
        team_id="T-ACTIVE",
        team_name="Research Workspace",
        bot_user_id="U-BOT",
        granted_scopes=frozenset(REQUIRED_SCOPES.split(",")),
        bot_token=SLACK_TOKEN,
    )
    channel = SlackChannel(
        id="C-OLD",
        team_id="T-REPLACED",
        name="historical-papers",
        is_private=False,
    )
    db_session.add(channel)
    db_session.commit()

    class FailIfCalledClient:
        async def conversation_info(self, channel_id):
            raise AssertionError("catch-up must not use active credentials for another team")

    count = _catch_up_channel(db_session, FailIfCalledClient(), workspace, channel)

    assert count == 0
