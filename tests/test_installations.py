import base64
import importlib
import importlib.util
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError


REQUIRED_SCOPES = {"channels:history", "channels:read", "users:read"}
ENCRYPTION_KEY = base64.urlsafe_b64encode(b"a" * 32).decode()
SLACK_TOKEN = "xoxb-secret-slack-token"
ZOTERO_API_KEY = "secret-zotero-api-key"


def _as_utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


def _contract():
    credentials_name = "app.services.credentials"
    installations_name = "app.services.installations"
    assert importlib.util.find_spec(credentials_name) is not None, (
        "F-13 requires app.services.credentials"
    )
    assert importlib.util.find_spec(installations_name) is not None, (
        "F-13 requires app.services.installations"
    )

    credentials = importlib.import_module(credentials_name)
    installations = importlib.import_module(installations_name)
    models = importlib.import_module("app.models")
    required_service_names = (
        "SlackWorkspaceContext",
        "ZoteroDestinationContext",
        "ActivationResult",
        "get_current_installation",
        "get_active_workspace_context",
        "get_verified_zotero_context",
        "activate_installation",
        "deactivate_installation",
        "configure_trial_zotero_destination",
    )
    for name in required_service_names:
        assert hasattr(installations, name), f"missing installation service contract: {name}"
    assert hasattr(models, "SlackInstallation")
    assert hasattr(models, "TrialZoteroDestination")
    return credentials.CredentialCipher, installations, models


def _cipher():
    CredentialCipher, _, _ = _contract()
    return CredentialCipher(ENCRYPTION_KEY)


def _installation(models, cipher, *, scopes=REQUIRED_SCOPES, active=False, team_id="T1"):
    token_column = next(
        (
            name
            for name in ("encrypted_bot_token", "bot_token_encrypted", "bot_token_ciphertext")
            if name in models.SlackInstallation.__table__.columns
        ),
        None,
    )
    assert token_column is not None, "SlackInstallation needs an encrypted bot-token column"
    values = {
        "team_id": team_id,
        "team_name": f"Workspace {team_id}",
        "bot_user_id": "U-BOT",
        "granted_scopes": ",".join(sorted(scopes)),
        "credential_status": "valid",
        "is_active": active,
        token_column: cipher.encrypt(SLACK_TOKEN),
    }
    return models.SlackInstallation(**values)


def _configure_destination(db_session, installations, cipher, **overrides):
    values = {
        "group_id": "12345",
        "api_key": ZOTERO_API_KEY,
        "cipher": cipher,
        "verification_succeeded": True,
        "verification_error": None,
    }
    values.update(overrides)
    return installations.configure_trial_zotero_destination(db_session, **values)


def test_database_rejects_a_second_current_slack_installation(db_session):
    cipher = _cipher()
    _, _, models = _contract()
    db_session.add(_installation(models, cipher, team_id="T1"))
    db_session.commit()

    db_session.add(_installation(models, cipher, team_id="T2"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_rejects_a_second_trial_zotero_destination(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    _configure_destination(db_session, installations, cipher)
    db_session.commit()
    current = db_session.query(models.TrialZoteroDestination).one()
    duplicate_values = {
        column.name: getattr(current, column.name)
        for column in models.TrialZoteroDestination.__table__.columns
        if not column.primary_key
    }
    if "group_id" in duplicate_values:
        duplicate_values["group_id"] = "67890"

    with pytest.raises(IntegrityError):
        db_session.execute(insert(models.TrialZoteroDestination).values(**duplicate_values))
        db_session.commit()


def test_inactive_or_destinationless_installation_has_no_processing_context(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    installation = _installation(models, cipher, active=False)
    db_session.add(installation)
    db_session.commit()

    assert installations.get_current_installation(db_session) is installation
    assert (
        installations.get_active_workspace_context(
            db_session,
            team_id="T1",
            cipher=cipher,
        )
        is None
    )
    assert installations.get_verified_zotero_context(db_session, cipher=cipher) is None

    installation.is_active = True
    db_session.commit()

    assert (
        installations.get_active_workspace_context(
            db_session,
            team_id="T1",
            cipher=cipher,
        )
        is None
    )


def test_active_contexts_expose_only_the_matching_workspace_and_verified_destination(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    installation = _installation(models, cipher, active=True)
    db_session.add(installation)
    _configure_destination(db_session, installations, cipher)
    db_session.commit()
    destination_row = db_session.query(models.TrialZoteroDestination).one()

    workspace = installations.get_active_workspace_context(
        db_session,
        team_id="T1",
        cipher=cipher,
    )
    destination = installations.get_verified_zotero_context(db_session, cipher=cipher)

    assert isinstance(workspace, installations.SlackWorkspaceContext)
    assert workspace.team_id == "T1"
    assert workspace.bot_token == SLACK_TOKEN
    assert SLACK_TOKEN not in repr(workspace)
    assert (
        installations.get_active_workspace_context(
            db_session,
            team_id="T-UNKNOWN",
            cipher=cipher,
        )
        is None
    )
    assert isinstance(destination, installations.ZoteroDestinationContext)
    assert destination.group_id == "12345"
    assert destination.api_key == ZOTERO_API_KEY
    assert ZOTERO_API_KEY not in repr(destination)
    assert SLACK_TOKEN not in repr(
        {
            column.name: getattr(installation, column.name)
            for column in models.SlackInstallation.__table__.columns
        }
    )
    assert ZOTERO_API_KEY not in repr(
        {
            column.name: getattr(destination_row, column.name)
            for column in models.TrialZoteroDestination.__table__.columns
        }
    )


def test_activation_requires_every_public_channel_scope_and_verified_destination(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    installation = _installation(
        models,
        cipher,
        scopes=REQUIRED_SCOPES - {"users:read"},
    )
    db_session.add(installation)
    _configure_destination(db_session, installations, cipher)
    db_session.commit()

    result = installations.activate_installation(
        db_session,
        required_scopes=REQUIRED_SCOPES,
    )

    assert isinstance(result, installations.ActivationResult)
    assert result.activated is False
    assert "users:read" in result.reason
    assert installation.is_active is False

    installation.granted_scopes = ",".join(sorted(REQUIRED_SCOPES))
    db_session.commit()
    result = installations.activate_installation(
        db_session,
        required_scopes=REQUIRED_SCOPES,
    )

    assert result.activated is True
    assert installation.is_active is True
    assert installation.status_code == "active"
    assert installation.status_message == "Slack installation is active"
    assert installation.last_validated_at is not None
    assert installation.deactivated_at is None


def test_activation_fails_without_a_verified_destination(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    installation = _installation(models, cipher)
    db_session.add(installation)
    db_session.commit()
    validated_at = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    result = installations.activate_installation(
        db_session,
        required_scopes=REQUIRED_SCOPES,
        now=validated_at,
    )

    assert result.activated is False
    assert installation.is_active is False
    assert installation.status_code == "zotero_destination_required"
    assert _as_utc(installation.last_validated_at) == validated_at
    assert installation.deactivated_at is None


def test_failed_destination_verification_preserves_current_verified_destination(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    _configure_destination(db_session, installations, cipher)
    db_session.commit()
    original = installations.get_verified_zotero_context(db_session, cipher=cipher)

    _configure_destination(
        db_session,
        installations,
        cipher,
        group_id="67890",
        api_key="replacement-secret",
        verification_succeeded=False,
        verification_error="Zotero access could not be verified",
    )
    db_session.commit()

    preserved = installations.get_verified_zotero_context(db_session, cipher=cipher)
    assert db_session.query(models.TrialZoteroDestination).count() == 1
    assert preserved == original
    assert preserved.group_id == "12345"
    assert preserved.api_key == ZOTERO_API_KEY


def test_changing_verified_destination_clears_old_group_sync_mappings(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    _configure_destination(db_session, installations, cipher)
    paper = models.Paper(source_type="arxiv", source_id="1706.03762")
    channel = models.SlackChannel(
        id="C1",
        team_id="T1",
        name="reading",
        is_private=False,
    )
    db_session.add_all([paper, channel])
    db_session.flush()
    db_session.add_all(
        [
            models.ZoteroItemSync(
                paper_id=paper.id,
                zotero_item_key="I-OLD",
                zotero_note_key="N-OLD",
                sync_status="synced",
            ),
            models.ZoteroCollectionSync(
                channel_id=channel.id,
                zotero_collection_key="C-OLD",
                sync_status="synced",
            ),
        ]
    )
    db_session.commit()

    result = _configure_destination(
        db_session,
        installations,
        cipher,
        group_id="67890",
        api_key="replacement-secret",
    )

    assert result.configured is True
    assert db_session.query(models.ZoteroItemSync).count() == 0
    assert db_session.query(models.ZoteroCollectionSync).count() == 0
    assert db_session.get(models.TrialZoteroDestination, 1).group_id == "67890"


def test_failed_initial_destination_verification_records_only_safe_status(db_session):
    cipher = _cipher()
    _, installations, models = _contract()

    result = _configure_destination(
        db_session,
        installations,
        cipher,
        verification_succeeded=False,
        verification_error=f"Zotero rejected api_key={ZOTERO_API_KEY}",
    )

    destination = db_session.query(models.TrialZoteroDestination).one()
    assert result.configured is False
    assert ZOTERO_API_KEY not in result.reason
    assert destination.status == "verification_failed"
    assert destination.status_code == "access_not_verified"
    assert ZOTERO_API_KEY not in destination.status_message
    assert destination.last_validated_at is not None
    assert destination.verified_at is None


def test_deactivation_removes_processing_context_without_deleting_installation(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    installation = _installation(models, cipher, active=True)
    db_session.add(installation)
    _configure_destination(db_session, installations, cipher)
    db_session.commit()
    validated_at = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    deactivated_at = datetime(2026, 7, 23, 13, 0, tzinfo=timezone.utc)
    installation.last_validated_at = validated_at
    db_session.commit()

    result = installations.deactivate_installation(db_session, now=deactivated_at)

    assert isinstance(result, installations.ActivationResult)
    assert result.activated is False
    assert installation.status_code == "manually_deactivated"
    assert _as_utc(installation.deactivated_at) == deactivated_at
    assert _as_utc(installation.last_validated_at) == validated_at
    assert db_session.query(models.SlackInstallation).one() is installation
    assert (
        installations.get_active_workspace_context(
            db_session,
            team_id="T1",
            cipher=cipher,
        )
        is None
    )


def test_channel_and_user_gain_team_id_without_rekeying_slack_ids(db_session):
    _, _, models = _contract()
    now = datetime.now(timezone.utc)
    channel = models.SlackChannel(
        id="C123",
        team_id="T1",
        name="papers",
        is_private=False,
        first_seen_at=now,
    )
    user = models.SlackUser(
        id="U123",
        team_id="T1",
        display_name="Ada",
        real_name="Ada Lovelace",
        first_seen_at=now,
    )
    db_session.add_all([channel, user])
    db_session.commit()

    assert db_session.get(models.SlackChannel, "C123").team_id == "T1"
    assert db_session.get(models.SlackUser, "U123").team_id == "T1"
    assert channel.id == "C123"
    assert user.id == "U123"


def test_f13_models_store_safe_lifecycle_state_without_plaintext_credentials(db_session):
    cipher = _cipher()
    _, installations, models = _contract()
    installation = _installation(models, cipher)
    installation.app_id = "A123"
    installation.last_oauth_attempt_at = datetime.now(timezone.utc)
    db_session.add(installation)
    _configure_destination(
        db_session,
        installations,
        cipher,
        group_name="Research Group",
        api_base_url="https://api.zotero.org/",
    )
    attempt = models.SlackOAuthAttempt(
        state_hash="a" * 64,
        purpose="replace",
        expected_team_id="T-OLD",
        status="completed",
        result_code="installed",
        result_message="Slack workspace authorization completed",
        result_team_id="T1",
        expires_at=datetime.now(timezone.utc),
        claimed_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        replacement_approved=True,
    )
    db_session.add(attempt)
    db_session.commit()

    destination = db_session.query(models.TrialZoteroDestination).one()
    assert installation.app_id == "A123"
    assert installation.credential_status == "valid"
    assert installation.last_oauth_attempt_at is not None
    assert not hasattr(installation, "bot_token")
    assert destination.group_name == "Research Group"
    assert destination.api_base_url == "https://api.zotero.org"
    assert destination.status == "verified"
    assert destination.status_code == "access_verified"
    assert destination.last_validated_at == destination.verified_at
    assert not hasattr(destination, "api_key")
    assert attempt.purpose == "replace"
    assert attempt.expected_team_id == "T-OLD"
    assert attempt.status == "completed"
    assert attempt.result_team_id == "T1"
    assert attempt.claimed_at is not None
    assert attempt.completed_at is not None
    assert not hasattr(attempt, "state")
