from datetime import datetime, timedelta, timezone
from importlib import import_module

import pytest

from app.models import (
    IngestionEvent,
    Paper,
    PaperCitation,
    RelatedPaperRun,
    RelatedPaperSuggestion,
    SlackChannel,
    SlackInstallation,
    SlackMention,
    SlackOAuthAttempt,
    SlackUser,
    TrialZoteroDestination,
    ZoteroCollectionSync,
    ZoteroItemSync,
)


def _reset_credentials_module():
    return import_module("scripts.reset_credentials")


def _seed_credentials(db_session):
    installation = SlackInstallation(
        team_id="T-KEEP",
        team_name="Workspace to keep",
        bot_user_id="U-BOT",
        encrypted_bot_token="encrypted-slack-token",
        granted_scopes="channels:history,channels:read,users:read",
        credential_status="valid",
        is_active=True,
        status_code="active",
        status_message="Slack installation is active",
    )
    destination = TrialZoteroDestination(
        group_id="123456",
        group_name="Research Group",
        encrypted_api_key="encrypted-zotero-key",
        is_verified=True,
        status="verified",
        status_code="verified",
        status_message="Zotero destination is verified",
    )
    oauth_attempt = SlackOAuthAttempt(
        state_hash="a" * 64,
        status="completed",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db_session.add_all([installation, destination, oauth_attempt])
    db_session.commit()
    return installation, destination, oauth_attempt


def _seed_archive(db_session):
    paper = Paper(
        source_type="arxiv",
        source_id="1706.03762",
        metadata_status="complete",
    )
    channel = SlackChannel(
        id="C1",
        team_id="T-KEEP",
        name="papers",
        is_private=False,
    )
    user = SlackUser(id="U1", team_id="T-KEEP", display_name="Researcher")
    db_session.add_all([paper, channel, user])
    db_session.flush()
    db_session.add_all(
        [
            PaperCitation(
                paper_id=paper.id,
                bibtex="@article{paper}",
                provider="crossref",
                source_url="https://doi.org/10.1000/example",
            ),
            SlackMention(
                paper_id=paper.id,
                team_id="T-KEEP",
                channel_id=channel.id,
                channel_name=channel.name,
                user_id=user.id,
                user_name=user.display_name,
                message_ts="123.456",
                original_url="https://arxiv.org/abs/1706.03762",
            ),
            IngestionEvent(key="Ev1", source="slack", status="processed"),
            ZoteroCollectionSync(
                channel_id=channel.id,
                zotero_collection_key="COLLECTION",
                sync_status="synced",
            ),
            ZoteroItemSync(
                paper_id=paper.id,
                zotero_item_key="ITEM",
                zotero_note_key="NOTE",
                sync_status="synced",
            ),
            RelatedPaperRun(
                paper_id=paper.id,
                status="complete",
                changed_since_zotero_sync=True,
            ),
        ]
    )
    db_session.flush()
    db_session.add(
        RelatedPaperSuggestion(
            paper_id=paper.id,
            suggested_paper_id="S2:example",
            rank=1,
            title="Related paper",
        )
    )
    db_session.commit()
    return paper


def _assert_archive_present(db_session):
    for model in (
        Paper,
        PaperCitation,
        SlackChannel,
        SlackUser,
        SlackMention,
        IngestionEvent,
        RelatedPaperRun,
        RelatedPaperSuggestion,
    ):
        assert db_session.query(model).count() == 1


def _assert_archive_cleared(db_session):
    for model in (
        RelatedPaperSuggestion,
        RelatedPaperRun,
        ZoteroItemSync,
        ZoteroCollectionSync,
        PaperCitation,
        SlackMention,
        IngestionEvent,
        Paper,
        SlackChannel,
        SlackUser,
    ):
        assert db_session.query(model).count() == 0


def test_ordinary_archive_reset_clears_dependents_and_preserves_credentials(db_session):
    reset_archive = import_module("scripts.reset_archive")
    installation, destination, oauth_attempt = _seed_credentials(db_session)
    _seed_archive(db_session)

    reset_archive.reset_archive(db_session)

    _assert_archive_cleared(db_session)
    preserved_installation = db_session.get(SlackInstallation, installation.id)
    preserved_destination = db_session.get(TrialZoteroDestination, destination.id)
    assert preserved_installation is installation
    assert preserved_installation.is_active is True
    assert preserved_installation.status_code == "active"
    assert preserved_destination is destination
    assert preserved_destination.status == "verified"
    assert db_session.get(SlackOAuthAttempt, oauth_attempt.id) is oauth_attempt


@pytest.mark.parametrize(
    "confirmation",
    [None, "", "yes", "DELETE", "reset credentials", "full-credential-reset"],
)
def test_reset_credentials_rejects_everything_except_literal_confirmation(
    db_session,
    confirmation,
):
    reset_credentials = _reset_credentials_module()
    installation, destination, oauth_attempt = _seed_credentials(db_session)
    _seed_archive(db_session)

    with pytest.raises(ValueError, match="literal confirmation"):
        reset_credentials.reset_credentials(db_session, confirmation)

    assert db_session.get(SlackInstallation, installation.id) is installation
    assert db_session.get(TrialZoteroDestination, destination.id) is destination
    assert db_session.get(SlackOAuthAttempt, oauth_attempt.id) is oauth_attempt
    _assert_archive_present(db_session)
    assert db_session.query(ZoteroItemSync).count() == 1
    assert db_session.query(ZoteroCollectionSync).count() == 1


def test_reset_credentials_removes_credentials_and_mappings_but_preserves_archive(
    db_session,
):
    reset_credentials = _reset_credentials_module()
    _seed_credentials(db_session)
    paper = _seed_archive(db_session)

    reset_credentials.reset_credentials(
        db_session,
        reset_credentials.FULL_RESET_CONFIRMATION,
    )

    assert db_session.query(SlackInstallation).count() == 0
    assert db_session.query(TrialZoteroDestination).count() == 0
    assert db_session.query(SlackOAuthAttempt).count() == 0
    assert db_session.query(ZoteroItemSync).count() == 0
    assert db_session.query(ZoteroCollectionSync).count() == 0
    _assert_archive_present(db_session)
    assert db_session.get(Paper, paper.id) is paper


def test_reset_credentials_can_include_archive(db_session):
    reset_credentials = _reset_credentials_module()
    _seed_credentials(db_session)
    _seed_archive(db_session)

    reset_credentials.reset_credentials(
        db_session,
        reset_credentials.FULL_RESET_CONFIRMATION,
        include_archive=True,
    )

    assert db_session.query(SlackInstallation).count() == 0
    assert db_session.query(TrialZoteroDestination).count() == 0
    assert db_session.query(SlackOAuthAttempt).count() == 0
    _assert_archive_cleared(db_session)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--confirm", "yes"],
        ["--confirm", "full-credential-reset"],
    ],
)
def test_credential_reset_cli_requires_exact_explicit_confirmation(
    db_session,
    monkeypatch,
    argv,
):
    reset_credentials = _reset_credentials_module()
    _seed_credentials(db_session)
    monkeypatch.setattr(reset_credentials, "init_db", lambda: None)

    with pytest.raises(SystemExit):
        reset_credentials.main(argv)

    assert db_session.query(SlackInstallation).count() == 1
    assert db_session.query(TrialZoteroDestination).count() == 1


def test_credential_reset_cli_reports_reauthorization_requirement(
    db_session,
    monkeypatch,
    capsys,
):
    reset_credentials = _reset_credentials_module()
    _seed_credentials(db_session)

    class SessionContext:
        def __enter__(self):
            return db_session

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(reset_credentials, "init_db", lambda: None)
    monkeypatch.setattr(reset_credentials, "SessionLocal", SessionContext)

    reset_credentials.main(
        ["--confirm", reset_credentials.FULL_RESET_CONFIRMATION]
    )

    assert "Slack must be authorized again" in capsys.readouterr().out
