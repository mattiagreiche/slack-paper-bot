import pytest

from app.config import get_settings
from app.extractors.base import PaperMetadata
from app.models import Paper, SlackChannel
from app.services.ingestion import SlackMessage, ingest_slack_message
from app.services.installations import SlackWorkspaceContext, ZoteroDestinationContext
from app.services.metadata import refresh_pending_metadata
from app.worker import _refresh_metadata_for_runtime


def _message(
    *,
    team_id: str,
    channel_id: str,
    user_id: str,
    source_id: str,
    message_ts: str,
) -> SlackMessage:
    return SlackMessage(
        team_id=team_id,
        channel_id=channel_id,
        channel_name=channel_id.lower(),
        channel_is_private=False,
        user_id=user_id,
        user_name=user_id.lower(),
        message_ts=message_ts,
        thread_ts=None,
        text=f"https://arxiv.org/abs/{source_id}",
    )


class FakeExtractor:
    async def fetch_metadata(self, source_key):
        return PaperMetadata(
            source_type=source_key.source_type,
            source_id=source_key.source_id,
            title=f"Metadata {source_key.source_id}",
            authors=["Ada Lovelace"],
            abstract="Scoped metadata.",
            categories=["cs.LG"],
            primary_category="cs.LG",
            published_at=None,
            updated_at=None,
            canonical_url=source_key.canonical_url,
            pdf_url=source_key.pdf_url,
        )


@pytest.mark.asyncio
async def test_metadata_refresh_only_selects_public_mentions_from_active_team(
    db_session,
    monkeypatch,
):
    ingest_slack_message(
        db_session,
        _message(
            team_id="T-ACTIVE",
            channel_id="C-ACTIVE",
            user_id="U-ACTIVE",
            source_id="1706.03762",
            message_ts="1716216600.000100",
        ),
    )
    ingest_slack_message(
        db_session,
        _message(
            team_id="T-OLD",
            channel_id="C-OLD",
            user_id="U-OLD",
            source_id="2309.08600",
            message_ts="1716216700.000100",
        ),
    )
    ingest_slack_message(
        db_session,
        _message(
            team_id="T-ACTIVE",
            channel_id="C-PRIVATE",
            user_id="U-PRIVATE",
            source_id="2401.12345",
            message_ts="1716216800.000100",
        ),
    )
    db_session.get(SlackChannel, "C-PRIVATE").is_private = True
    db_session.commit()

    monkeypatch.setattr(
        "app.services.metadata.extractor_for_source",
        lambda source: FakeExtractor(),
    )

    async def no_citation(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.metadata.refresh_citation", no_citation)
    monkeypatch.setattr(get_settings(), "arxiv_request_delay_seconds", 0)

    refreshed = await refresh_pending_metadata(db_session, team_id="T-ACTIVE")

    papers = {
        paper.source_id: paper
        for paper in db_session.query(Paper).order_by(Paper.source_id).all()
    }
    assert refreshed == 1
    assert papers["1706.03762"].metadata_status == "ready"
    assert papers["2309.08600"].metadata_status == "pending"
    assert papers["2401.12345"].metadata_status == "pending"


@pytest.mark.asyncio
async def test_metadata_refresh_without_team_context_does_no_external_work(
    db_session,
    monkeypatch,
):
    ingest_slack_message(
        db_session,
        _message(
            team_id="T-ACTIVE",
            channel_id="C-ACTIVE",
            user_id="U-ACTIVE",
            source_id="1706.03762",
            message_ts="1716216600.000100",
        ),
    )
    monkeypatch.setattr(
        "app.services.metadata.extractor_for_source",
        lambda source: pytest.fail("metadata extractor must not run without team context"),
    )

    assert await refresh_pending_metadata(db_session, team_id=None) == 0
    assert db_session.query(Paper).one().metadata_status == "pending"


@pytest.mark.asyncio
async def test_metadata_failure_records_exception_type_when_message_is_empty(
    db_session,
    monkeypatch,
):
    ingest_slack_message(
        db_session,
        _message(
            team_id="T-ACTIVE",
            channel_id="C-ACTIVE",
            user_id="U-ACTIVE",
            source_id="2006.01855",
            message_ts="1716216600.000100",
        ),
    )

    class TimeoutExtractor:
        async def fetch_metadata(self, source_key):
            raise TimeoutError

    monkeypatch.setattr(
        "app.services.metadata.extractor_for_source",
        lambda source: TimeoutExtractor(),
    )
    monkeypatch.setattr(get_settings(), "arxiv_request_delay_seconds", 0)

    assert await refresh_pending_metadata(db_session, team_id="T-ACTIVE") == 0
    paper = db_session.query(Paper).one()
    assert paper.metadata_status == "failed"
    assert paper.metadata_error == "TimeoutError"
    assert paper.metadata_attempts == 1
    assert paper.next_metadata_retry_at is not None


def test_worker_metadata_refresh_requires_workspace_and_destination(monkeypatch):
    calls = []

    def fake_refresh(db, *, team_id):
        calls.append((db, team_id))
        return 2

    monkeypatch.setattr("app.worker.refresh_pending_metadata_sync", fake_refresh)
    workspace = SlackWorkspaceContext(
        team_id="T-ACTIVE",
        team_name="Active Workspace",
        bot_user_id="U-BOT",
        granted_scopes=frozenset(),
        bot_token="xoxb-test",
    )
    destination = ZoteroDestinationContext(
        group_id="12345",
        api_key="zotero-test",
    )

    assert _refresh_metadata_for_runtime("db", None, destination) == 0
    assert _refresh_metadata_for_runtime("db", workspace, None) == 0
    assert calls == []
    assert _refresh_metadata_for_runtime("db", workspace, destination) == 2
    assert calls == [("db", "T-ACTIVE")]
