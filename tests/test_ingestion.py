from datetime import datetime, timezone

from app.extractors.base import PaperMetadata
from app.models import Paper, SlackMention
from app.services.ingestion import SlackMessage, extract_urls, ingest_slack_message
from app.services.metadata import apply_metadata
from app.services.search import search_papers


def test_extract_urls_handles_slack_wrapped_and_bare_links():
    text = "Read <https://arxiv.org/abs/1706.03762|paper> and https://example.com/x."
    assert extract_urls(text) == ["https://arxiv.org/abs/1706.03762", "https://example.com/x"]


def test_ingestion_dedupes_same_paper_across_mentions(db_session):
    first = SlackMessage(
        team_id="T1",
        channel_id="C1",
        channel_name="reading",
        channel_is_private=False,
        user_id="U1",
        user_name="Ada",
        message_ts="1716216600.000100",
        thread_ts=None,
        text="https://arxiv.org/abs/1706.03762v5",
        permalink="https://slack.example/1",
    )
    second = SlackMessage(
        team_id="T1",
        channel_id="C2",
        channel_name="models",
        channel_is_private=False,
        user_id="U2",
        user_name="Noa",
        message_ts="1716217600.000200",
        thread_ts=None,
        text="<https://arxiv.org/pdf/1706.03762.pdf|pdf>",
        permalink="https://slack.example/2",
    )

    assert ingest_slack_message(db_session, first) == 1
    assert ingest_slack_message(db_session, second) == 1

    papers = db_session.query(Paper).all()
    mentions = db_session.query(SlackMention).all()
    assert len(papers) == 1
    assert papers[0].source_id == "1706.03762"
    assert len(mentions) == 2


def test_ingestion_accepts_doi_and_semantic_scholar_links(db_session):
    doi_message = SlackMessage(
        team_id="T1",
        channel_id="C1",
        channel_name="reading",
        channel_is_private=False,
        user_id="U1",
        user_name="Ada",
        message_ts="1716216600.000100",
        thread_ts=None,
        text="https://doi.org/10.1145/3366423.3380138",
    )
    semantic_scholar_message = SlackMessage(
        team_id="T1",
        channel_id="C1",
        channel_name="reading",
        channel_is_private=False,
        user_id="U1",
        user_name="Ada",
        message_ts="1716217600.000200",
        thread_ts=None,
        text="https://www.semanticscholar.org/paper/Attention/Vaswani/204e3073870fae3d05bcbc2f6a8e263d9b72e776",
    )

    assert ingest_slack_message(db_session, doi_message) == 1
    assert ingest_slack_message(db_session, semantic_scholar_message) == 1

    papers = sorted(db_session.query(Paper).all(), key=lambda paper: paper.source_type)
    assert [(paper.source_type, paper.source_id) for paper in papers] == [
        ("doi", "10.1145/3366423.3380138"),
        ("semantic_scholar", "204e3073870fae3d05bcbc2f6a8e263d9b72e776"),
    ]


def test_same_message_does_not_duplicate_when_backfill_has_no_workspace_or_url_changes(db_session):
    first = SlackMessage(
        team_id=None,
        channel_id="C1",
        channel_name="reading",
        channel_is_private=False,
        user_id="U1",
        user_name=None,
        message_ts="1716216600.000100",
        thread_ts=None,
        text="https://arxiv.org/abs/1706.03762",
        permalink=None,
    )
    second = SlackMessage(
        team_id="T1",
        channel_id="C1",
        channel_name="reading",
        channel_is_private=False,
        user_id="U1",
        user_name="Ada",
        message_ts="1716216600.000100",
        thread_ts=None,
        text="<https://arxiv.org/pdf/1706.03762.pdf|pdf>",
        permalink="https://slack.example/1",
    )

    assert ingest_slack_message(db_session, first) == 1
    assert ingest_slack_message(db_session, second) == 0

    mentions = db_session.query(SlackMention).all()
    assert len(mentions) == 1
    assert mentions[0].team_id == "T1"
    assert mentions[0].user_name == "Ada"
    assert mentions[0].slack_permalink == "https://slack.example/1"


def test_multiple_uncommitted_messages_share_pending_channel(db_session):
    first = SlackMessage(
        team_id="T1",
        channel_id="C1",
        channel_name="reading",
        channel_is_private=False,
        user_id="U1",
        user_name="Ada",
        message_ts="1716216600.000100",
        thread_ts=None,
        text="https://arxiv.org/abs/1706.03762",
    )
    second = SlackMessage(
        team_id="T1",
        channel_id="C1",
        channel_name="reading",
        channel_is_private=False,
        user_id="U1",
        user_name="Ada",
        message_ts="1716217600.000200",
        thread_ts=None,
        text="https://arxiv.org/abs/2309.08600",
    )

    ingest_slack_message(db_session, first, commit=False)
    ingest_slack_message(db_session, second, commit=False)
    db_session.commit()

    assert len(db_session.query(SlackMention).all()) == 2


def test_search_filters_and_mention_count(db_session):
    msg = SlackMessage(
        team_id="T1",
        channel_id="C1",
        channel_name="interpretability",
        channel_is_private=False,
        user_id="U1",
        user_name="Ada",
        message_ts="1716216600.000100",
        thread_ts=None,
        text="https://arxiv.org/abs/2309.08600",
    )
    ingest_slack_message(db_session, msg)
    paper = db_session.query(Paper).one()
    apply_metadata(
        paper,
        PaperMetadata(
            source_type="arxiv",
            source_id="2309.08600",
            title="Towards Monosemanticity",
            authors=["Trenton Bricken"],
            abstract="Sparse autoencoders decompose language model activations.",
            categories=["cs.LG"],
            primary_category="cs.LG",
            published_at=datetime(2023, 9, 15, tzinfo=timezone.utc),
            updated_at=datetime(2023, 9, 15, tzinfo=timezone.utc),
            canonical_url="https://arxiv.org/abs/2309.08600",
            pdf_url="https://arxiv.org/pdf/2309.08600.pdf",
        ),
    )
    db_session.commit()

    results = search_papers(db_session, query="autoencoders", channel_id="C1", user="Ada")
    assert len(results) == 1
    assert results[0].mention_count == 1
    assert results[0].paper.title == "Towards Monosemanticity"
