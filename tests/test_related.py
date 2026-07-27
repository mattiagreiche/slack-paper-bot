from datetime import datetime, timezone

import pytest

from app.extractors.base import PaperMetadata
from app.models import Paper, RelatedPaperRun, RelatedPaperSuggestion, ZoteroItemSync
from app.services.ingestion import SlackMessage, ingest_slack_message
from app.services.metadata import apply_metadata
from app.services.related import (
    RelatedPaper,
    RelatedPaperError,
    RelatedPaperUnavailable,
    ensure_related_run,
    parse_recommendations,
    query_id_for_paper,
    refresh_pending_related_papers,
    semantic_scholar_source_url,
)
from app.services.zotero import render_bot_note


class FakeRelatedClient:
    def __init__(self, papers=None, exc=None):
        self.papers = papers or []
        self.exc = exc
        self.calls = []

    async def recommendations_for_paper(self, paper_id, *, limit):
        self.calls.append((paper_id, limit))
        if self.exc:
            raise self.exc
        return self.papers


def _synced_arxiv_paper(db_session) -> Paper:
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
            permalink="https://slack.example/archives/C1/p1716216600000100",
        ),
    )
    paper = db_session.query(Paper).one()
    apply_metadata(
        paper,
        PaperMetadata(
            source_type="arxiv",
            source_id="1706.03762",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            abstract="Transformer architecture.",
            categories=["cs.CL"],
            primary_category="cs.CL",
            published_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
            updated_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
            canonical_url="https://arxiv.org/abs/1706.03762",
            pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
        ),
    )
    db_session.add(
        ZoteroItemSync(
            paper_id=paper.id,
            zotero_item_key="I1",
            zotero_note_key="N1",
            sync_status="synced",
            last_synced_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    return paper


def _synced_team_paper(
    db_session,
    *,
    team_id,
    channel_id,
    source_id,
    message_ts,
) -> Paper:
    ingest_slack_message(
        db_session,
        SlackMessage(
            team_id=team_id,
            channel_id=channel_id,
            channel_name=f"reading-{team_id}",
            channel_is_private=False,
            user_id=f"U-{team_id}",
            user_name="Ada",
            message_ts=message_ts,
            thread_ts=None,
            text=f"https://arxiv.org/abs/{source_id}",
        ),
    )
    paper = db_session.query(Paper).filter_by(source_id=source_id).one()
    apply_metadata(
        paper,
        PaperMetadata(
            source_type="arxiv",
            source_id=source_id,
            title=f"Paper {source_id}",
            authors=["Ada Lovelace"],
            abstract="Research abstract.",
            categories=["cs.CL"],
            primary_category="cs.CL",
            published_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            updated_at=None,
            canonical_url=f"https://arxiv.org/abs/{source_id}",
            pdf_url=None,
        ),
    )
    db_session.add(
        ZoteroItemSync(
            paper_id=paper.id,
            zotero_item_key=f"I-{team_id}",
            zotero_note_key=f"N-{team_id}",
            sync_status="synced",
            last_synced_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    return paper


def _related_paper(paper_id="recommended-1", *, arxiv=None) -> RelatedPaper:
    external_ids = {"DOI": "10.1000/example"}
    if arxiv:
        external_ids["ArXiv"] = arxiv
    return RelatedPaper(
        paper_id=paper_id,
        title="A Recommended Paper",
        authors=["Grace Hopper", "Alan Turing", "Katherine Johnson"],
        year=2020,
        publication_date="2020-01-02",
        venue="NeurIPS",
        url=f"https://www.semanticscholar.org/paper/{paper_id}",
        abstract="A useful related paper.",
        external_ids=external_ids,
        citation_count=42,
        fields_of_study=["Computer Science"],
        publication_types=["Conference"],
    )


def test_query_id_for_supported_sources(db_session):
    arxiv = Paper(source_type="arxiv", source_id="1706.03762")
    doi = Paper(source_type="doi", source_id="10.1000/example")
    semantic_scholar = Paper(source_type="semantic_scholar", source_id="abc123")
    unsupported = Paper(source_type="openreview", source_id="xyz")

    assert query_id_for_paper(arxiv) == "ArXiv:1706.03762"
    assert query_id_for_paper(doi) == "DOI:10.1000/example"
    assert query_id_for_paper(semantic_scholar) == "abc123"
    assert query_id_for_paper(unsupported) is None


def test_semantic_scholar_source_url_uses_exact_page_for_semantic_scholar_items():
    paper = Paper(source_type="semantic_scholar", source_id="abc123")

    assert semantic_scholar_source_url(paper) == "https://www.semanticscholar.org/paper/abc123"


def test_semantic_scholar_source_url_falls_back_to_title_search():
    paper = Paper(
        source_type="arxiv",
        source_id="1706.03762",
        title="Attention Is All You Need",
    )

    assert semantic_scholar_source_url(paper) == (
        "https://www.semanticscholar.org/search?q=Attention+Is+All+You+Need&sort=relevance"
    )


def test_parse_recommendations_handles_missing_optional_fields():
    papers = parse_recommendations(
        {
            "recommendedPapers": [
                {
                    "paperId": "p1",
                    "title": "Sparse Metadata",
                    "authors": [{"name": "Ada Lovelace"}],
                }
            ]
        }
    )

    assert len(papers) == 1
    assert papers[0].paper_id == "p1"
    assert papers[0].title == "Sparse Metadata"
    assert papers[0].authors == ["Ada Lovelace"]
    assert papers[0].external_ids == {}


@pytest.mark.asyncio
async def test_refresh_related_papers_stores_suggestions_and_filters_self(db_session, monkeypatch):
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "related_papers_enabled", True)
    monkeypatch.setattr(settings, "related_papers_limit", 5)
    paper = _synced_arxiv_paper(db_session)
    client = FakeRelatedClient(
        papers=[
            _related_paper("self", arxiv="1706.03762"),
            _related_paper("recommended-1"),
        ]
    )

    refreshed = await refresh_pending_related_papers(db_session, client=client)

    assert refreshed == 1
    assert client.calls == [("ArXiv:1706.03762", 6)]
    run = db_session.get(RelatedPaperRun, paper.id)
    suggestions = db_session.query(RelatedPaperSuggestion).all()
    assert run.status == "ready"
    assert run.changed_since_zotero_sync is True
    assert len(suggestions) == 1
    assert suggestions[0].suggested_paper_id == "recommended-1"
    assert suggestions[0].rank == 1
    assert suggestions[0].authors.splitlines()[0] == "Grace Hopper"


@pytest.mark.asyncio
async def test_refresh_related_papers_records_unavailable_without_retry(db_session, monkeypatch):
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "related_papers_enabled", True)
    paper = _synced_arxiv_paper(db_session)
    client = FakeRelatedClient(exc=RelatedPaperUnavailable("not found"))

    refreshed = await refresh_pending_related_papers(db_session, client=client)

    run = db_session.get(RelatedPaperRun, paper.id)
    assert refreshed == 1
    assert run.status == "unavailable"
    assert run.next_retry_at is None
    assert "not found" in run.error


@pytest.mark.asyncio
async def test_refresh_related_papers_records_temporary_failure(db_session, monkeypatch):
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "related_papers_enabled", True)
    paper = _synced_arxiv_paper(db_session)
    client = FakeRelatedClient(exc=RelatedPaperError("rate-limited"))

    refreshed = await refresh_pending_related_papers(db_session, client=client)

    run = db_session.get(RelatedPaperRun, paper.id)
    assert refreshed == 1
    assert run.status == "failed"
    assert run.next_retry_at is not None
    assert run.changed_since_zotero_sync is True
    assert "rate-limited" in run.error


@pytest.mark.asyncio
async def test_related_refresh_excludes_old_workspace_only_records(db_session, monkeypatch):
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "related_papers_enabled", True)
    old_paper = _synced_team_paper(
        db_session,
        team_id="T-OLD",
        channel_id="C-OLD",
        source_id="1706.03762",
        message_ts="1716216600.000100",
    )
    active_paper = _synced_team_paper(
        db_session,
        team_id="T-ACTIVE",
        channel_id="C-ACTIVE",
        source_id="2301.00001",
        message_ts="1716216700.000100",
    )
    client = FakeRelatedClient(papers=[_related_paper()])
    assert ensure_related_run(db_session, old_paper, team_id="T-ACTIVE") is None
    db_session.add(RelatedPaperRun(paper_id=old_paper.id, status="pending"))
    db_session.commit()

    refreshed = await refresh_pending_related_papers(
        db_session,
        client=client,
        team_id="T-ACTIVE",
    )

    assert refreshed == 1
    assert client.calls == [("ArXiv:2301.00001", 6)]
    assert db_session.get(RelatedPaperRun, active_paper.id) is not None
    assert db_session.get(RelatedPaperRun, old_paper.id).status == "pending"


def test_bot_note_renders_related_suggestions_without_debug_details(db_session):
    paper = _synced_arxiv_paper(db_session)
    run = RelatedPaperRun(paper_id=paper.id, status="ready", error="secret stack trace")
    suggestion = RelatedPaperSuggestion(
        paper_id=paper.id,
        suggested_paper_id="recommended-1",
        rank=1,
        title="A Recommended Paper",
        authors="Grace Hopper\nAlan Turing\nKatherine Johnson",
        year=2020,
        venue="NeurIPS",
        url="https://www.semanticscholar.org/paper/recommended-1",
        external_ids='{"ArXiv": "2001.00001", "DOI": "10.1000/example"}',
    )

    note = render_bot_note(
        paper,
        paper.mentions,
        related_run=run,
        related_suggestions=[suggestion],
    )

    assert "Related papers (bot-generated via Semantic Scholar)" in note
    assert "View this paper on Semantic Scholar" in note
    assert "https://www.semanticscholar.org/search?q=Attention+Is+All+You+Need" in note
    assert "Bot-generated note for" not in note
    assert "bot-generated via Semantic Scholar" in note
    assert "A Recommended Paper" in note
    assert "Grace Hopper, Alan Turing, et al." in note
    assert "DOI: 10.1000/example" in note
    assert "secret stack trace" not in note
