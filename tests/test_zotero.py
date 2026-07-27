from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from httpx import Response

from app.config import Settings
from app.extractors.base import PaperMetadata
from app.models import (
    Paper,
    RelatedPaperRun,
    RelatedPaperSuggestion,
    SlackChannel,
    SlackInstallation,
    TrialZoteroDestination,
    ZoteroCollectionSync,
    ZoteroItemSync,
)
from app.services.credentials import CredentialCipher
from app.services.ingestion import SlackMessage, ingest_slack_message
from app.services.metadata import apply_metadata
from app.services.zotero import (
    ZoteroApiError,
    ZoteroApiClient,
    ZoteroSettings,
    render_bot_note,
    sync_paper_to_zotero,
    sync_ready_papers_to_zotero,
    verify_zotero_destination,
)


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

    async def find_bot_note(self, item_key):
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


class AuthenticationFailureZoteroClient(FakeZoteroClient):
    def __init__(self, status_code=401):
        super().__init__()
        self.status_code = status_code
        self.calls = 0

    async def find_item_by_extra_marker(self, marker):
        self.calls += 1
        raise ZoteroApiError(
            f"Zotero rejected access with {self.status_code}",
            status_code=self.status_code,
        )


def _ready_paper(
    db_session,
    *,
    team_id="T1",
    channel_id="C1",
    channel_name="reading",
    user_id="U1",
    source_id="1706.03762",
    message_ts="1716216600.000100",
) -> Paper:
    ingest_slack_message(
        db_session,
        SlackMessage(
            team_id=team_id,
            channel_id=channel_id,
            channel_name=channel_name,
            channel_is_private=False,
            user_id=user_id,
            user_name="Ada",
            message_ts=message_ts,
            thread_ts=None,
            text=f"https://arxiv.org/abs/{source_id}",
            permalink=f"https://slack.example/archives/{channel_id}/p{message_ts}",
        ),
    )
    paper = db_session.query(Paper).filter_by(source_id=source_id).one()
    apply_metadata(
        paper,
        PaperMetadata(
            source_type="arxiv",
            source_id=source_id,
            title=f"Paper {source_id}",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            abstract="Transformer architecture.",
            categories=["cs.CL"],
            primary_category="cs.CL",
            published_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
            updated_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
            canonical_url=f"https://arxiv.org/abs/{source_id}",
            pdf_url=f"https://arxiv.org/pdf/{source_id}.pdf",
        ),
    )
    db_session.commit()
    return paper


def _active_installation_and_destination(db_session, monkeypatch):
    encryption_key = Fernet.generate_key().decode("ascii")
    cipher = CredentialCipher(encryption_key)
    monkeypatch.setattr(
        __import__("app.config", fromlist=["get_settings"]).get_settings(),
        "credential_encryption_key",
        encryption_key,
    )
    db_session.add(
        SlackInstallation(
            id=1,
            team_id="T1",
            team_name="Active workspace",
            bot_user_id="U-BOT",
            encrypted_bot_token=cipher.encrypt("xoxb-test"),
            granted_scopes="channels:history,channels:read,users:read",
            credential_status="valid",
            is_active=True,
            status_code="active",
            status_message="Slack installation is active",
        )
    )
    db_session.add(
        TrialZoteroDestination(
            id=1,
            group_id="12345",
            group_name="Research Group",
            api_base_url="https://zotero.example",
            encrypted_api_key=cipher.encrypt("persisted-zotero-key"),
            is_verified=True,
            status="verified",
            status_code="access_verified",
            status_message="Zotero destination access is verified",
        )
    )
    db_session.commit()


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
    assert client.items[0]["title"] == "Paper 1706.03762"
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
async def test_automatic_sync_uses_persisted_destination(db_session, monkeypatch):
    _ready_paper(db_session)
    _active_installation_and_destination(db_session, monkeypatch)
    client = FakeZoteroClient()
    captured = []

    def client_factory(settings):
        captured.append(settings)
        return client

    monkeypatch.setattr("app.services.zotero.ZoteroApiClient", client_factory)

    synced = await sync_ready_papers_to_zotero(db_session)

    assert synced == 1
    assert captured[0].api_key == "persisted-zotero-key"
    assert captured[0].group_id == "12345"
    assert captured[0].api_base_url == "https://zotero.example"


@pytest.mark.asyncio
async def test_automatic_sync_does_not_fall_back_to_environment_destination(
    db_session,
    monkeypatch,
):
    _ready_paper(db_session)
    settings = Settings()
    assert not hasattr(settings, "zotero_api_key")
    assert not hasattr(settings, "zotero_group_id")

    def unexpected_client(_settings):
        pytest.fail("environment Zotero settings must not construct a client")

    monkeypatch.setattr("app.services.zotero.ZoteroApiClient", unexpected_client)

    assert await sync_ready_papers_to_zotero(db_session) == 0


@pytest.mark.asyncio
async def test_destination_verification_checks_key_write_access_without_leaking_key(
    monkeypatch,
):
    client = ZoteroApiClient(
        ZoteroSettings(
            api_key="zotero-secret",
            group_id="12345",
            api_base_url="https://zotero.example",
        )
    )

    async def fake_request(method, path, **_kwargs):
        assert method == "GET"
        if path == "/keys/current":
            return Response(
                200,
                json={
                    "access": {
                        "groups": {
                            "12345": {
                                "library": True,
                                "write": True,
                            }
                        }
                    }
                },
            )
        assert path == "/groups/12345"
        return Response(200, json={"data": {"name": "Research Group"}})

    monkeypatch.setattr(client, "request", fake_request)

    assert await client.verify_destination() == "Research Group"
    assert "zotero-secret" not in repr(
        await verify_zotero_destination(group_id="", api_key="zotero-secret")
    )


@pytest.mark.asyncio
async def test_bot_note_recovery_ignores_human_notes_that_only_mention_title(monkeypatch):
    client = ZoteroApiClient(
        ZoteroSettings(
            api_key="zotero-test",
            group_id="12345",
            api_base_url="https://zotero.example",
        )
    )

    async def fake_request(method, path, **kwargs):
        assert method == "GET"
        assert path.endswith("/items/I1/children")
        return Response(
            200,
            json=[
                {
                    "key": "N-HUMAN",
                    "data": {
                        "itemType": "note",
                        "note": "<p>Discussion of the phrase Bot notes.</p>",
                    },
                },
                {
                    "key": "N-BOT",
                    "data": {
                        "itemType": "note",
                        "note": "<h1>Bot notes</h1><p>Slack shares</p>",
                    },
                },
            ],
        )

    monkeypatch.setattr(client, "request", fake_request)

    assert await client.find_bot_note("I1") == "N-BOT"


@pytest.mark.parametrize("status_code", [401, 403])
@pytest.mark.asyncio
async def test_zotero_auth_failure_invalidates_destination_and_stops_batch(
    db_session,
    monkeypatch,
    status_code,
):
    _ready_paper(db_session, source_id="1706.03762")
    _ready_paper(
        db_session,
        channel_id="C2",
        channel_name="papers",
        source_id="2301.00001",
        message_ts="1716216700.000100",
    )
    _active_installation_and_destination(db_session, monkeypatch)
    client = AuthenticationFailureZoteroClient(status_code)

    synced = await sync_ready_papers_to_zotero(
        db_session,
        client=client,
        team_id="T1",
    )

    destination = db_session.get(TrialZoteroDestination, 1)
    failed_syncs = db_session.query(ZoteroItemSync).all()
    assert synced == 0
    assert client.calls == 1
    assert destination.is_verified is False
    assert destination.status == "invalid"
    assert destination.status_code == "access_revoked"
    assert len(failed_syncs) == 1
    assert failed_syncs[0].sync_status == "failed"


@pytest.mark.asyncio
async def test_zotero_sync_excludes_old_workspace_only_records(db_session):
    _ready_paper(
        db_session,
        team_id="T-OLD",
        channel_id="C-OLD",
        channel_name="old-reading",
        source_id="1706.03762",
    )
    _ready_paper(
        db_session,
        team_id="T-ACTIVE",
        channel_id="C-ACTIVE",
        channel_name="active-reading",
        user_id="U-ACTIVE",
        source_id="2301.00001",
        message_ts="1716216700.000100",
    )
    client = FakeZoteroClient()

    synced = await sync_ready_papers_to_zotero(
        db_session,
        client=client,
        team_id="T-ACTIVE",
    )

    assert synced == 1
    assert client.collections == ["active-reading"]
    assert len(client.items) == 1
    assert client.items[0]["title"] == "Paper 2301.00001"
    assert "old-reading" not in client.notes[0][1]


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
async def test_zotero_sync_refreshes_note_for_related_suggestions_without_auto_import(db_session):
    paper = _ready_paper(db_session)
    db_session.add(
        RelatedPaperRun(
            paper_id=paper.id,
            status="ready",
            changed_since_zotero_sync=True,
        )
    )
    db_session.add(
        RelatedPaperSuggestion(
            paper_id=paper.id,
            suggested_paper_id="recommended-1",
            rank=1,
            title="A Recommended Paper",
            authors="Grace Hopper\nAlan Turing",
            year=2020,
            venue="NeurIPS",
            url="https://www.semanticscholar.org/paper/recommended-1",
        )
    )
    db_session.add(
        ZoteroItemSync(
            paper_id=paper.id,
            zotero_item_key="I-existing",
            zotero_note_key="N-existing",
            sync_status="synced",
            last_synced_at=datetime(2017, 6, 13, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    client = FakeZoteroClient()

    synced = await sync_ready_papers_to_zotero(db_session, client=client)

    run = db_session.get(RelatedPaperRun, paper.id)
    assert synced == 1
    assert client.items == []
    assert len(client.note_updates) == 1
    assert "A Recommended Paper" in client.note_updates[0][1]
    assert "Related papers (bot-generated via Semantic Scholar)" in client.note_updates[0][1]
    assert run.changed_since_zotero_sync is False


@pytest.mark.asyncio
async def test_zotero_sync_skips_private_channel_mentions(db_session):
    paper = _ready_paper(db_session)
    paper.mentions[0].channel_name = "private-reading"
    paper.mentions[0].channel_id = "C1"
    db_session.get(SlackChannel, "C1").is_private = True
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
    assert "Bot-generated note for" not in note


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
