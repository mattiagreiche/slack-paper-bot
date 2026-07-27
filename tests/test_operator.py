from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.auth import auth_token
from app.database import get_db
from app.extractors.base import PaperMetadata
from app.main import app
from app.models import Paper, RelatedPaperRun, SlackChannel, ZoteroItemSync
from app.services.ingestion import SlackMessage, ingest_slack_message
from app.services.metadata import apply_metadata
from app.services.operator import redact_error


def _client(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _auth_cookie():
    return {"paper_archive_auth": auth_token()}


def _paper(db_session) -> Paper:
    ingest_slack_message(
        db_session,
        SlackMessage(
            team_id="T1",
            channel_id="C1",
            channel_name="reading",
            channel_is_private=False,
            user_id="U1",
            user_name="Ada",
            message_ts="1716216600.000100",
            thread_ts=None,
            text="https://arxiv.org/abs/1706.03762",
        ),
    )
    return db_session.query(Paper).one()


def _ready_paper(db_session) -> Paper:
    paper = _paper(db_session)
    apply_metadata(
        paper,
        PaperMetadata(
            source_type="arxiv",
            source_id="1706.03762",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani"],
            abstract="Transformer architecture.",
            categories=["cs.CL"],
            primary_category="cs.CL",
            published_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
            updated_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
            canonical_url="https://arxiv.org/abs/1706.03762",
            pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
        ),
    )
    db_session.commit()
    return paper


def test_status_shows_operator_work_without_leaking_secrets(db_session):
    paper = _paper(db_session)
    paper.metadata_status = "failed"
    paper.metadata_error = "provider failed token=zotero-secret"
    paper.next_metadata_retry_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db_session.commit()

    client = _client(db_session)
    response = client.get("/status", cookies=_auth_cookie())

    assert response.status_code == 200
    assert "Metadata work" in response.text
    assert "Retry metadata" in response.text
    assert "provider failed" in response.text
    assert "zotero-secret" not in response.text
    assert "token=[redacted]" in response.text


def test_operator_error_redaction_covers_generic_api_keys_and_tokens():
    redacted = redact_error(
        "provider failed api_key=zotero-secret token=slack-secret"
    )

    assert "zotero-secret" not in redacted
    assert "slack-secret" not in redacted
    assert "api_key=[redacted]" in redacted
    assert "token=[redacted]" in redacted


def test_status_formats_slack_channel_timestamps(db_session):
    _paper(db_session)
    channel = db_session.get(SlackChannel, "C1")
    channel.last_backfilled_ts = "1783364300.000000"
    channel.last_catchup_ts = "1783364396.922339"
    db_session.commit()
    expected_backfill = datetime.fromtimestamp(
        float(channel.last_backfilled_ts), tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")
    expected_catchup = datetime.fromtimestamp(
        float(channel.last_catchup_ts), tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    client = _client(db_session)
    response = client.get("/status", cookies=_auth_cookie())

    assert response.status_code == 200
    assert expected_backfill in response.text
    assert expected_catchup in response.text
    assert channel.last_backfilled_ts not in response.text
    assert channel.last_catchup_ts not in response.text


def test_retry_metadata_marks_paper_pending_for_worker(db_session):
    paper = _paper(db_session)
    paper.metadata_status = "failed"
    paper.metadata_error = "Crossref failed"
    paper.next_metadata_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    client = _client(db_session)
    response = client.post(
        f"/operator/papers/{paper.id}/retry-metadata",
        cookies=_auth_cookie(),
        follow_redirects=False,
    )
    db_session.refresh(paper)

    assert response.status_code == 303
    assert response.headers["location"] == "/status"
    assert paper.metadata_status == "pending"
    assert paper.metadata_error is None
    assert paper.next_metadata_retry_at is None


def test_retry_zotero_marks_sync_pending_for_worker(db_session):
    paper = _ready_paper(db_session)
    original_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    sync = ZoteroItemSync(
        paper_id=paper.id,
        zotero_item_key="I1",
        sync_status="failed",
        sync_error="Zotero failed",
        next_sync_retry_at=original_retry_at,
    )
    db_session.add(sync)
    db_session.commit()

    client = _client(db_session)
    response = client.post(
        f"/operator/papers/{paper.id}/retry-zotero",
        cookies=_auth_cookie(),
        follow_redirects=False,
    )
    db_session.refresh(sync)

    assert response.status_code == 303
    assert response.headers["location"] == "/status"
    assert sync.sync_status == "pending"
    assert sync.sync_error is None
    assert sync.next_sync_retry_at is not None
    assert sync.next_sync_retry_at < original_retry_at.replace(tzinfo=None)


def test_retry_related_marks_run_pending_for_worker(db_session):
    paper = _ready_paper(db_session)
    run = RelatedPaperRun(
        paper_id=paper.id,
        status="failed",
        error="Semantic Scholar failed",
        next_retry_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(run)
    db_session.commit()

    client = _client(db_session)
    response = client.post(
        f"/operator/papers/{paper.id}/retry-related",
        cookies=_auth_cookie(),
        follow_redirects=False,
    )
    db_session.refresh(run)

    assert response.status_code == 303
    assert response.headers["location"] == "/status"
    assert run.status == "pending"
    assert run.error is None
    assert run.next_retry_at is None


def test_retry_routes_require_authentication(db_session):
    paper = _paper(db_session)
    paper.metadata_status = "failed"
    db_session.commit()

    client = _client(db_session)
    response = client.post(
        f"/operator/papers/{paper.id}/retry-metadata",
        follow_redirects=False,
    )
    db_session.refresh(paper)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert paper.metadata_status == "failed"
