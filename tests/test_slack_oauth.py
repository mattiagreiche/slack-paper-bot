import base64
from datetime import datetime, timedelta, timezone
import hashlib
from importlib import import_module
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


REQUIRED_SCOPES = {"channels:history", "channels:read", "users:read"}
NOW = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)
ENCRYPTION_KEY = base64.urlsafe_b64encode(b"o" * 32).decode()

# Register the OAuth tables before the shared fixture creates SQLAlchemy metadata.
import_module("app.models")


def _as_utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


class FakeOAuthExchange:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, *, code, redirect_uri):
        self.calls.append({"code": code, "redirect_uri": redirect_uri})
        return self.response


def _future_contract():
    try:
        oauth = import_module("app.services.slack_oauth")
        models = import_module("app.models")
        return (
            oauth.begin_slack_oauth,
            oauth.complete_slack_oauth,
            oauth.OAuthStart,
            oauth.OAuthCompletion,
            models.SlackInstallation,
            models.SlackOAuthAttempt,
        )
    except (ImportError, AttributeError) as exc:
        pytest.fail(f"F-13 Slack OAuth contract is not implemented: {exc}", pytrace=False)


def _begin(db_session, *, replacement_approved=False, now=NOW):
    begin, _, OAuthStart, _, _, _ = _future_contract()
    result = begin(
        db_session,
        client_id="client-123",
        redirect_uri="https://archive.example/slack/oauth/callback",
        replacement_approved=replacement_approved,
        now=now,
        state_ttl=timedelta(minutes=10),
    )
    assert isinstance(result, OAuthStart)
    return result


def _complete(db_session, start, exchange, *, state=None, code="oauth-code", error=None, now=NOW):
    _, complete, _, OAuthCompletion, _, _ = _future_contract()
    CredentialCipher = import_module("app.services.credentials").CredentialCipher
    result = complete(
        db_session,
        state=start.state if state is None else state,
        code=code,
        error=error,
        redirect_uri="https://archive.example/slack/oauth/callback",
        exchange_code=exchange,
        cipher=CredentialCipher(ENCRYPTION_KEY),
        now=now,
    )
    assert isinstance(result, OAuthCompletion)
    return result


def _slack_success(*, team_id="T-TEST", token="xoxb-new", scopes=REQUIRED_SCOPES):
    return {
        "ok": True,
        "app_id": "A-ARCHIVE",
        "access_token": token,
        "scope": ",".join(sorted(scopes)),
        "bot_user_id": "U-BOT",
        "team": {"id": team_id, "name": f"Workspace {team_id}"},
    }


def _verified_destination(db_session):
    models = import_module("app.models")
    cipher = import_module("app.services.credentials").CredentialCipher(ENCRYPTION_KEY)
    destination = models.TrialZoteroDestination(
        id=1,
        group_id="12345",
        api_base_url="https://api.zotero.org",
        encrypted_api_key=cipher.encrypt("zotero-secret"),
        is_verified=True,
        status="verified",
        status_code="access_verified",
        status_message="Zotero destination access is verified",
    )
    db_session.add(destination)
    db_session.commit()
    return destination


def _file_session_factory(tmp_path):
    Base = import_module("app.database").Base
    engine = create_engine(
        f"sqlite:///{tmp_path / 'slack-oauth.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_begin_oauth_uses_only_required_scopes_and_persists_hashed_expiring_state(db_session):
    start = _begin(db_session)
    _, _, _, _, _, SlackOAuthAttempt = _future_contract()

    query = parse_qs(urlparse(start.authorization_url).query)
    assert set(query["scope"][0].split(",")) == REQUIRED_SCOPES
    assert query["state"] == [start.state]
    assert query["client_id"] == ["client-123"]
    assert query["redirect_uri"] == ["https://archive.example/slack/oauth/callback"]
    assert "user_scope" not in query

    attempt = db_session.query(SlackOAuthAttempt).one()
    assert attempt.state_hash == hashlib.sha256(start.state.encode()).hexdigest()
    assert attempt.state_hash != start.state
    assert attempt.purpose == "install"
    assert attempt.expected_team_id is None
    assert attempt.status == "pending"
    assert _as_utc(attempt.expires_at) == NOW + timedelta(minutes=10)
    assert attempt.claimed_at is None
    assert attempt.completed_at is None
    assert attempt.replacement_approved is False


def test_successful_oauth_creates_single_inactive_installation(db_session):
    start = _begin(db_session)
    exchange = FakeOAuthExchange(_slack_success())

    completion = _complete(db_session, start, exchange)
    _, _, _, _, SlackInstallation, SlackOAuthAttempt = _future_contract()

    assert completion.success is True
    assert completion.team_id == "T-TEST"
    assert exchange.calls == [
        {
            "code": "oauth-code",
            "redirect_uri": "https://archive.example/slack/oauth/callback",
        }
    ]
    installation = db_session.query(SlackInstallation).one()
    assert installation.team_id == "T-TEST"
    assert not hasattr(installation, "bot_token")
    assert installation.encrypted_bot_token != "xoxb-new"
    assert (
        import_module("app.services.credentials")
        .CredentialCipher(ENCRYPTION_KEY)
        .decrypt(installation.encrypted_bot_token)
        == "xoxb-new"
    )
    assert installation.bot_user_id == "U-BOT"
    assert installation.app_id == "A-ARCHIVE"
    assert set(installation.granted_scopes.split(",")) == REQUIRED_SCOPES
    assert installation.is_active is False
    attempt = db_session.query(SlackOAuthAttempt).one()
    assert _as_utc(attempt.claimed_at) == NOW
    assert _as_utc(attempt.completed_at) == NOW
    assert attempt.status == "succeeded"
    assert attempt.result_team_id == "T-TEST"


def test_successful_oauth_accepts_and_records_additional_granted_scopes(db_session):
    start = _begin(db_session)
    granted_scopes = REQUIRED_SCOPES | {"chat:write"}

    completion = _complete(
        db_session,
        start,
        FakeOAuthExchange(_slack_success(scopes=granted_scopes)),
    )
    _, _, _, _, SlackInstallation, _ = _future_contract()

    assert completion.success is True
    installation = db_session.query(SlackInstallation).one()
    assert set(installation.granted_scopes.split(",")) == granted_scopes


@pytest.mark.parametrize(
    ("callback", "expected_message"),
    [
        ({"error": "access_denied", "code": None}, "denied"),
        ({"state": "forged-state"}, "state"),
    ],
)
def test_denial_or_mismatched_state_does_not_exchange_or_install(
    db_session,
    callback,
    expected_message,
):
    start = _begin(db_session)
    exchange = FakeOAuthExchange(_slack_success())

    completion = _complete(db_session, start, exchange, **callback)
    _, _, _, _, SlackInstallation, _ = _future_contract()

    assert completion.success is False
    assert expected_message in completion.message.lower()
    assert exchange.calls == []
    assert db_session.query(SlackInstallation).count() == 0


def test_expired_state_is_rejected_without_exchange(db_session):
    start = _begin(db_session)
    exchange = FakeOAuthExchange(_slack_success())

    completion = _complete(db_session, start, exchange, now=NOW + timedelta(minutes=11))
    _, _, _, _, SlackInstallation, _ = _future_contract()

    assert completion.success is False
    assert "expired" in completion.message.lower()
    assert exchange.calls == []
    assert db_session.query(SlackInstallation).count() == 0


def test_oauth_state_is_one_time_even_after_success(db_session):
    start = _begin(db_session)
    first_exchange = FakeOAuthExchange(_slack_success())
    second_exchange = FakeOAuthExchange(_slack_success(token="xoxb-should-not-win"))

    assert _complete(db_session, start, first_exchange).success is True
    duplicate = _complete(db_session, start, second_exchange)
    _, _, _, _, SlackInstallation, _ = _future_contract()

    assert duplicate.success is False
    assert "state" in duplicate.message.lower()
    assert second_exchange.calls == []
    encrypted_token = db_session.query(SlackInstallation).one().encrypted_bot_token
    assert "xoxb-new" not in encrypted_token


def test_same_team_reinstall_updates_single_row_and_remains_inactive(db_session):
    first = _begin(db_session)
    _complete(db_session, first, FakeOAuthExchange(_slack_success(token="xoxb-old")))
    _, _, _, _, SlackInstallation, _ = _future_contract()
    existing = db_session.query(SlackInstallation).one()
    existing.is_active = True
    db_session.commit()

    second = _begin(db_session)
    completion = _complete(
        db_session,
        second,
        FakeOAuthExchange(_slack_success(token="xoxb-rotated")),
    )

    assert completion.success is True
    assert db_session.query(SlackInstallation).count() == 1
    installation = db_session.query(SlackInstallation).one()
    assert installation.team_id == "T-TEST"
    cipher = import_module("app.services.credentials").CredentialCipher(ENCRYPTION_KEY)
    assert cipher.decrypt(installation.encrypted_bot_token) == "xoxb-rotated"
    assert installation.is_active is False


def test_different_team_is_rejected_without_operator_approved_replacement(db_session):
    first = _begin(db_session)
    _complete(db_session, first, FakeOAuthExchange(_slack_success(token="xoxb-old")))

    second = _begin(db_session)
    completion = _complete(
        db_session,
        second,
        FakeOAuthExchange(_slack_success(team_id="T-MILA", token="xoxb-mila")),
    )
    _, _, _, _, SlackInstallation, _ = _future_contract()

    assert completion.success is False
    assert "workspace" in completion.message.lower()
    installation = db_session.query(SlackInstallation).one()
    assert installation.team_id == "T-TEST"
    cipher = import_module("app.services.credentials").CredentialCipher(ENCRYPTION_KEY)
    assert cipher.decrypt(installation.encrypted_bot_token) == "xoxb-old"


def test_operator_approved_replacement_installs_new_team_inactive(db_session):
    first = _begin(db_session)
    _complete(db_session, first, FakeOAuthExchange(_slack_success(token="xoxb-old")))
    _, _, _, _, SlackInstallation, SlackOAuthAttempt = _future_contract()
    _verified_destination(db_session)
    installed = db_session.query(SlackInstallation).one()
    installed.is_active = True
    db_session.commit()

    replacement = _begin(db_session, replacement_approved=True)
    completion = _complete(
        db_session,
        replacement,
        FakeOAuthExchange(_slack_success(team_id="T-MILA", token="xoxb-mila")),
    )

    assert completion.success is True
    assert db_session.query(SlackInstallation).count() == 1
    installation = db_session.query(SlackInstallation).one()
    assert installation.team_id == "T-MILA"
    cipher = import_module("app.services.credentials").CredentialCipher(ENCRYPTION_KEY)
    assert cipher.decrypt(installation.encrypted_bot_token) == "xoxb-mila"
    assert installation.is_active is False
    attempts = db_session.query(SlackOAuthAttempt).order_by(SlackOAuthAttempt.created_at).all()
    assert attempts[-1].replacement_approved is True
    assert attempts[-1].purpose == "replace"
    assert attempts[-1].expected_team_id == "T-TEST"


def test_older_callback_does_not_overwrite_newer_successful_authorization(db_session):
    older = _begin(db_session)
    newer = _begin(db_session, now=NOW + timedelta(seconds=1))
    _, complete, _, OAuthCompletion, SlackInstallation, _ = _future_contract()
    CredentialCipher = import_module("app.services.credentials").CredentialCipher

    newer_result = complete(
        db_session,
        state=newer.state,
        code="newer-code",
        error=None,
        redirect_uri="https://archive.example/slack/oauth/callback",
        exchange_code=FakeOAuthExchange(_slack_success(token="xoxb-newer")),
        cipher=CredentialCipher(ENCRYPTION_KEY),
        now=NOW + timedelta(seconds=2),
    )
    older_result = complete(
        db_session,
        state=older.state,
        code="older-code",
        error=None,
        redirect_uri="https://archive.example/slack/oauth/callback",
        exchange_code=FakeOAuthExchange(_slack_success(token="xoxb-older")),
        cipher=CredentialCipher(ENCRYPTION_KEY),
        now=NOW + timedelta(seconds=3),
    )

    assert isinstance(newer_result, OAuthCompletion)
    assert newer_result.success is True
    assert older_result.success is False
    installation = db_session.query(SlackInstallation).one()
    assert (
        CredentialCipher(ENCRYPTION_KEY).decrypt(installation.encrypted_bot_token)
        == "xoxb-newer"
    )


def test_any_newer_attempt_supersedes_older_authorization(db_session):
    older = _begin(db_session)
    newer = _begin(db_session, now=NOW + timedelta(seconds=1))

    newer_result = _complete(
        db_session,
        newer,
        lambda **kwargs: {"ok": False, "error": "temporary_failure"},
        now=NOW + timedelta(seconds=2),
    )
    older_exchange = FakeOAuthExchange(_slack_success())
    older_result = _complete(
        db_session,
        older,
        older_exchange,
        now=NOW + timedelta(seconds=3),
    )

    assert newer_result.success is False
    assert older_result.success is False
    assert older_exchange.calls == []


def test_newer_attempt_supersedes_older_callback_across_file_sqlite_sessions(tmp_path):
    Session = _file_session_factory(tmp_path)
    with Session() as begin_session:
        older = _begin(begin_session)
        newer = _begin(begin_session, now=NOW + timedelta(seconds=1))

    with Session() as newer_session:
        newer_result = _complete(
            newer_session,
            newer,
            FakeOAuthExchange(_slack_success(token="xoxb-newer")),
            now=NOW + timedelta(seconds=2),
        )

    older_exchange = FakeOAuthExchange(_slack_success(token="xoxb-older"))
    with Session() as older_session:
        older_result = _complete(
            older_session,
            older,
            older_exchange,
            now=NOW + timedelta(seconds=3),
        )

    with Session() as inspection_session:
        SlackInstallation = import_module("app.models").SlackInstallation
        installation = inspection_session.query(SlackInstallation).one()
        cipher = import_module("app.services.credentials").CredentialCipher(ENCRYPTION_KEY)
        assert cipher.decrypt(installation.encrypted_bot_token) == "xoxb-newer"

    assert newer_result.success is True
    assert older_result.success is False
    assert older_exchange.calls == []


def test_first_install_singleton_collision_returns_safe_failure(
    tmp_path,
    monkeypatch,
):
    Session = _file_session_factory(tmp_path)
    with Session() as begin_session:
        start = _begin(begin_session)

    primary_session = Session()
    real_commit = primary_session.commit
    commit_count = 0
    provider_token = "xoxb-provider-token-must-not-leak"

    def commit_with_competing_insert():
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            models = import_module("app.models")
            cipher = import_module("app.services.credentials").CredentialCipher(
                ENCRYPTION_KEY
            )
            with Session() as competing_session:
                competing_session.add(
                    models.SlackInstallation(
                        id=1,
                        app_id="A-ARCHIVE",
                        team_id="T-TEST",
                        team_name="Workspace T-TEST",
                        bot_user_id="U-COMPETING",
                        encrypted_bot_token=cipher.encrypt("xoxb-competing"),
                        granted_scopes=",".join(sorted(REQUIRED_SCOPES)),
                        credential_status="valid",
                        is_active=False,
                    )
                )
                competing_session.commit()
            IntegrityError = import_module("sqlalchemy.exc").IntegrityError
            raise IntegrityError("singleton insert", {}, RuntimeError("collision"))
        real_commit()

    monkeypatch.setattr(primary_session, "commit", commit_with_competing_insert)
    try:
        completion = _complete(
            primary_session,
            start,
            FakeOAuthExchange(_slack_success(token=provider_token)),
        )
        SlackOAuthAttempt = import_module("app.models").SlackOAuthAttempt
        attempt = primary_session.query(SlackOAuthAttempt).one()
    finally:
        primary_session.close()

    assert completion.success is False
    assert provider_token not in completion.message
    assert provider_token not in (attempt.result_message or "")
    with Session() as inspection_session:
        SlackInstallation = import_module("app.models").SlackInstallation
        assert inspection_session.query(SlackInstallation).count() == 1


def test_active_same_workspace_reauthorization_stays_active_with_verified_destination(
    db_session,
):
    first = _begin(db_session)
    _complete(db_session, first, FakeOAuthExchange(_slack_success(token="xoxb-old")))
    _, _, _, _, SlackInstallation, _ = _future_contract()
    _verified_destination(db_session)
    installation = db_session.query(SlackInstallation).one()
    installation.is_active = True
    installation.status_code = "active"
    installation.status_message = "Slack installation is active"
    db_session.commit()

    reinstall = _begin(db_session, now=NOW + timedelta(seconds=1))
    completion = _complete(
        db_session,
        reinstall,
        FakeOAuthExchange(_slack_success(token="xoxb-rotated")),
        now=NOW + timedelta(seconds=2),
    )

    assert completion.success is True
    assert "remains active" in completion.message
    assert installation.is_active is True
    assert installation.status_code == "active"


def test_same_workspace_reauthorization_deactivates_when_destination_is_unverified(
    db_session,
):
    first = _begin(db_session)
    _complete(db_session, first, FakeOAuthExchange(_slack_success(token="xoxb-old")))
    _, _, _, _, SlackInstallation, _ = _future_contract()
    destination = _verified_destination(db_session)
    installation = db_session.query(SlackInstallation).one()
    installation.is_active = True
    destination.is_verified = False
    destination.status = "verification_failed"
    db_session.commit()

    reinstall = _begin(db_session, now=NOW + timedelta(seconds=1))
    completion = _complete(
        db_session,
        reinstall,
        FakeOAuthExchange(_slack_success(token="xoxb-rotated")),
        now=NOW + timedelta(seconds=2),
    )

    assert completion.success is True
    assert installation.is_active is False
    assert installation.status_code == "zotero_destination_required"


def test_invalid_scope_reauthorization_deactivates_without_replacing_token(db_session):
    first = _begin(db_session)
    _complete(db_session, first, FakeOAuthExchange(_slack_success(token="xoxb-old")))
    _, _, _, _, SlackInstallation, _ = _future_contract()
    _verified_destination(db_session)
    installation = db_session.query(SlackInstallation).one()
    installation.is_active = True
    original_ciphertext = installation.encrypted_bot_token
    db_session.commit()

    reinstall = _begin(db_session, now=NOW + timedelta(seconds=1))
    completion = _complete(
        db_session,
        reinstall,
        FakeOAuthExchange(
            _slack_success(
                token="xoxb-invalid-scopes",
                scopes=REQUIRED_SCOPES - {"users:read"},
            )
        ),
        now=NOW + timedelta(seconds=2),
    )

    assert completion.success is False
    assert "users:read" in completion.message
    assert installation.is_active is False
    assert installation.status_code == "invalid_oauth_scopes"
    assert "users:read" in installation.status_message
    assert installation.encrypted_bot_token == original_ciphertext


def test_additional_scope_reauthorization_preserves_active_installation(db_session):
    first = _begin(db_session)
    _complete(db_session, first, FakeOAuthExchange(_slack_success(token="xoxb-old")))
    _, _, _, _, SlackInstallation, _ = _future_contract()
    _verified_destination(db_session)
    installation = db_session.query(SlackInstallation).one()
    installation.is_active = True
    db_session.commit()

    reinstall = _begin(db_session, now=NOW + timedelta(seconds=1))
    completion = _complete(
        db_session,
        reinstall,
        FakeOAuthExchange(
            _slack_success(
                token="xoxb-rotated",
                scopes=REQUIRED_SCOPES | {"chat:write"},
            )
        ),
        now=NOW + timedelta(seconds=2),
    )

    assert completion.success is True
    assert installation.is_active is True
    assert installation.status_code == "active"


def test_plaintext_token_is_absent_from_models_results_and_errors(db_session):
    token = "xoxb-secret-that-must-not-leak"
    start = _begin(db_session)
    completion = _complete(
        db_session,
        start,
        FakeOAuthExchange(_slack_success(token=token)),
    )
    _, _, _, _, SlackInstallation, SlackOAuthAttempt = _future_contract()
    oauth = import_module("app.services.slack_oauth")
    installation = db_session.query(SlackInstallation).one()
    attempt = db_session.query(SlackOAuthAttempt).one()
    parsed_authorization = oauth._parse_authorization(_slack_success(token=token))

    assert token not in repr(completion)
    assert token not in repr(installation)
    assert token not in repr(attempt)
    assert token not in repr(parsed_authorization)
    assert token not in repr(
        {
            column.name: getattr(installation, column.name)
            for column in SlackInstallation.__table__.columns
        }
    )


def test_exchange_failure_records_only_a_safe_result(db_session):
    token = "xoxb-secret-in-provider-error"
    start = _begin(db_session)

    def failing_exchange(*, code, redirect_uri):
        raise RuntimeError(f"Slack rejected {token} for {code} at {redirect_uri}")

    completion = _complete(db_session, start, failing_exchange)
    _, _, _, _, SlackInstallation, SlackOAuthAttempt = _future_contract()
    attempt = db_session.query(SlackOAuthAttempt).one()

    assert completion.success is False
    assert db_session.query(SlackInstallation).count() == 0
    assert attempt.status == "exchange_failed"
    assert token not in completion.message
    assert token not in (attempt.result_message or "")


def test_async_exchange_callable_is_supported_and_state_is_claimed_first(db_session):
    start = _begin(db_session)
    _, _, _, _, _, SlackOAuthAttempt = _future_contract()

    async def async_exchange(*, code, redirect_uri):
        attempt = db_session.query(SlackOAuthAttempt).one()
        assert attempt.claimed_at is not None
        assert attempt.status == "claimed"
        return _slack_success()

    completion = _complete(db_session, start, async_exchange)

    assert completion.success is True
