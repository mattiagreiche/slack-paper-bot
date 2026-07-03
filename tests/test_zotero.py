from datetime import datetime, timezone

import pytest

from app.extractors.base import PaperMetadata
from app.models import Paper, ZoteroCollectionSync, ZoteroItemSync
from app.services.ingestion import SlackMessage, ingest_slack_message
from app.services.metadata import apply_metadata
from app.services.zotero import render_bot_note, sync_paper_to_zotero, sync_ready_papers_to_zotero


class FakeZoteroClient:
    def __init__(self):
        self.collections = []
        self.items = []
        self.notes = []
        self.collection_updates = []
        self.note_updates = []
        self.existing_item_key = None
        self.existing_note_key = None

    async def create_collection(self, name):
        self.collections.append(name)
        return f"C{len(self.collections)}"

    async def find_item_by_extra_marker(self, marker):
        return self.existing_item_key

    async def find_child_note_by_title(self, item_key, title):
        return self.existing_note_key

    async def create_item(self, payload):
        self.items.append(payload)
        return f"I{len(self.items)}"

    async def ensure_item_collections(self, item_key, collection_keys):
        self.collection_updates.append((item_key, collection_keys))

    async def create_child_note(self, parent_item_key, note_html):
        self.notes.append((parent_item_key, note_html))
        return f"N{len(self.notes)}"

    async def update_note(self, note_key, note_html):
        self.note_updates.append((note_key, note_html))


def _ready_paper(db_session) -> Paper:
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
    db_session.commit()
    return paper


@pytest.mark.asyncio
async def test_zotero_sync_creates_item_collection_and_bot_note(db_session):
    paper = _ready_paper(db_session)
    client = FakeZoteroClient()

    synced = await sync_paper_to_zotero(db_session, paper, client)
    db_session.commit()

    assert synced is True
    assert client.collections == ["reading"]
    assert len(client.items) == 1
    assert client.items[0]["collections"] == ["C1"]
    assert client.items[0]["title"] == "Attention Is All You Need"
    assert client.items[0]["creators"] == [
        {"creatorType": "author", "name": "Ashish Vaswani"},
        {"creatorType": "author", "name": "Noam Shazeer"},
    ]
    assert "Slack Paper Archive: arxiv:1706.03762" in client.items[0]["extra"]
    assert len(client.notes) == 1
    assert client.notes[0][0] == "I1"
    assert "Bot notes" in client.notes[0][1]
    assert "#reading" in client.notes[0][1]
    assert "Ada" in client.notes[0][1]
    assert "Slack message" in client.notes[0][1]
    assert "Transformer architecture" not in client.notes[0][1]

    item_sync = db_session.get(ZoteroItemSync, paper.id)
    collection_sync = db_session.get(ZoteroCollectionSync, "C1")
    assert item_sync.zotero_item_key == "I1"
    assert item_sync.zotero_note_key == "N1"
    assert item_sync.sync_status == "synced"
    assert collection_sync.zotero_collection_key == "C1"


@pytest.mark.asyncio
async def test_zotero_sync_candidates_do_not_repeat_synced_items(db_session):
    _ready_paper(db_session)
    client = FakeZoteroClient()

    first = await sync_ready_papers_to_zotero(db_session, client=client)
    second = await sync_ready_papers_to_zotero(db_session, client=client)

    assert first == 1
    assert second == 0
    assert len(client.items) == 1
    assert len(client.notes) == 1


@pytest.mark.asyncio
async def test_zotero_sync_reuses_existing_item_and_bot_note(db_session):
    paper = _ready_paper(db_session)
    client = FakeZoteroClient()
    client.existing_item_key = "I-existing"
    client.existing_note_key = "N-existing"

    synced = await sync_paper_to_zotero(db_session, paper, client)
    db_session.commit()

    assert synced is True
    assert client.items == []
    assert client.notes == []
    assert client.collection_updates == [("I-existing", ["C1"])]
    assert len(client.note_updates) == 1
    assert client.note_updates[0][0] == "N-existing"
    item_sync = db_session.get(ZoteroItemSync, paper.id)
    assert item_sync.zotero_item_key == "I-existing"
    assert item_sync.zotero_note_key == "N-existing"


@pytest.mark.asyncio
async def test_zotero_sync_skips_private_channel_mentions(db_session):
    ingest_slack_message(
        db_session,
        SlackMessage(
            team_id="T1",
            channel_id="G1",
            channel_name="private-reading",
            channel_is_private=True,
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
    client = FakeZoteroClient()

    synced = await sync_paper_to_zotero(db_session, paper, client)
    db_session.commit()

    assert synced is False
    assert client.items == []
    assert db_session.get(ZoteroItemSync, paper.id).sync_status == "skipped"


def test_bot_note_uses_provenance_without_message_text(db_session):
    paper = _ready_paper(db_session)
    mention = paper.mentions[0]
    mention.original_url = "https://arxiv.org/abs/1706.03762"
    note = render_bot_note(paper, [mention])

    assert "Bot notes" in note
    assert "#reading" in note
    assert "Slack message" in note
    assert "https://arxiv.org/abs/1706.03762" in note
    assert "Attention Is All You Need" in note


@pytest.mark.asyncio
async def test_zotero_payload_includes_doi_for_doi_items(db_session):
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
            text="https://doi.org/10.1145/3366423.3380138",
        ),
    )
    paper = db_session.query(Paper).one()
    apply_metadata(
        paper,
        PaperMetadata(
            source_type="doi",
            source_id="10.1145/3366423.3380138",
            title="A DOI Paper",
            authors=["Ada Lovelace"],
            abstract="A paper with a DOI.",
            categories=["Computer Science"],
            primary_category="Computer Science",
            published_at=datetime(2020, 4, 23, tzinfo=timezone.utc),
            updated_at=None,
            canonical_url="https://doi.org/10.1145/3366423.3380138",
            pdf_url=None,
        ),
    )
    db_session.commit()
    client = FakeZoteroClient()

    synced = await sync_paper_to_zotero(db_session, paper, client)

    assert synced is True
    assert client.items[0]["DOI"] == "10.1145/3366423.3380138"
    assert client.items[0]["publicationTitle"] == ""
    assert "Slack Paper Archive: doi:10.1145/3366423.3380138" in client.items[0]["extra"]
