from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.auth import auth_token
from app.database import get_db
from app.demo_data import apply_demo_fixtures
from app.extractors.base import PaperMetadata
from app.main import app
from app.models import Paper
from app.services.ingestion import SlackMessage, ingest_slack_message
from app.services.metadata import apply_metadata


def _client(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _auth_cookie():
    return {"paper_archive_auth": auth_token()}


def test_search_ignores_blank_dates(db_session):
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
    paper = db_session.query(Paper).one()
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

    client = _client(db_session)
    response = client.get(
        "/?q=attention&date_from=&date_to=&sort=recent",
        cookies=_auth_cookie(),
    )

    assert response.status_code == 200
    assert "Attention Is All You Need" in response.text

    partial = client.get(
        "/search/results?q=attention&date_from=&date_to=&sort=recent",
        cookies=_auth_cookie(),
    )
    assert partial.status_code == 200
    assert partial.json()["count"] == 1
    assert "Attention Is All You Need" in partial.json()["html"]


def test_demo_slack_post_uses_real_ingestion_path(db_session):
    client = _client(db_session)

    response = client.post(
        "/demo/slack",
        data={
            "channel_id": "CROBOT",
            "user_id": "UADA",
            "text": "saving this https://arxiv.org/abs/1706.03762",
        },
        cookies=_auth_cookie(),
        follow_redirects=False,
    )
    apply_demo_fixtures(db_session)

    assert response.status_code == 303
    assert db_session.query(Paper).filter(Paper.source_id == "1706.03762").count() == 1

    page = client.get("/demo/slack", cookies=_auth_cookie())
    assert "Recent simulated mentions" not in page.text
    assert "Known fixtures" not in page.text


def test_demo_fixtures_store_arxiv_style_citation(db_session):
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
    apply_demo_fixtures(db_session)
    db_session.commit()

    paper = db_session.query(Paper).one()
    assert paper.citation is not None
    assert paper.citation.provider == "arXiv API"
    assert "vaswani2023attentionneed" in paper.citation.bibtex

    client = _client(db_session)
    response = client.get(f"/papers/{paper.id}.bib", cookies=_auth_cookie())
    assert response.status_code == 200
    assert "vaswani2023attentionneed" in response.text
