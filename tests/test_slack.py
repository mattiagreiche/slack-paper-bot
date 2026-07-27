import time

import pytest

from app.config import Settings
from app.services.slack import (
    SlackApiError,
    SlackSignatureError,
    backfill_channel,
    enrich_slack_message,
    joined_channels,
    slack_message_from_event,
    verify_slack_signature,
)
from app.services.installations import SlackWorkspaceContext


def test_slack_message_from_channel_event():
    message = slack_message_from_event(
        {
            "type": "message",
            "channel_type": "channel",
            "channel": "C1",
            "user": "U1",
            "ts": "1716216600.000100",
            "text": "https://arxiv.org/abs/1706.03762",
        },
        "T1",
    )

    assert message is not None
    assert message.channel_id == "C1"
    assert message.team_id == "T1"


def test_slack_message_from_private_channel_event_is_ignored():
    message = slack_message_from_event(
        {
            "type": "message",
            "channel_type": "group",
            "channel": "G1",
            "user": "U1",
            "ts": "1716216600.000100",
            "text": "https://arxiv.org/abs/1706.03762",
        },
        "T1",
    )

    assert message is None


def test_slack_signature_rejects_missing_secret():
    with pytest.raises(SlackSignatureError):
        verify_slack_signature(
            body=b"{}",
            timestamp=str(int(time.time())),
            signature="v0=bad",
            settings=Settings(slack_signing_secret=None),
        )


class FakeSlackClient:
    async def conversation_info(self, channel_id):
        return {
            "id": channel_id,
            "name": "papers",
            "is_private": False,
            "is_member": True,
        }

    async def user_info(self, user_id):
        return {
            "id": user_id,
            "name": "ada",
            "profile": {"display_name": "Ada Lovelace", "real_name": "Ada Lovelace"},
        }

    async def permalink(self, channel_id, message_ts):
        return f"https://slack.example/{channel_id}/{message_ts}"


@pytest.mark.asyncio
async def test_enrich_slack_message_adds_names_and_permalink():
    message = slack_message_from_event(
        {
            "type": "message",
            "channel_type": "channel",
            "channel": "C1",
            "user": "U1",
            "ts": "1716216600.000100",
            "text": "https://arxiv.org/abs/1706.03762",
        },
        "T1",
    )

    enriched = await enrich_slack_message(message, FakeSlackClient())

    assert enriched.channel_name == "papers"
    assert enriched.user_name == "Ada Lovelace"
    assert enriched.permalink == "https://slack.example/C1/1716216600.000100"


class FakeListSlackClient:
    async def conversations(self, *, types="public_channel", limit=200):
        assert types == "public_channel"
        return [
            {"id": "C1", "name": "joined", "is_member": True},
            {"id": "C2", "name": "not-joined", "is_member": False},
        ]


@pytest.mark.asyncio
async def test_joined_channels_filters_to_membership():
    channels = await joined_channels(FakeListSlackClient())

    assert [channel["id"] for channel in channels] == ["C1"]


class FakePrivateSlackClient:
    async def conversation_info(self, channel_id):
        return {
            "id": channel_id,
            "name": "private-papers",
            "is_private": True,
            "is_member": True,
        }

    async def history(self, channel_id, *, oldest=None, latest=None, limit=200):
        raise AssertionError("Private channel history should not be read during the trial")


@pytest.mark.asyncio
async def test_backfill_channel_skips_private_channels(db_session):
    workspace = SlackWorkspaceContext(
        team_id="T1",
        team_name="Workspace",
        bot_user_id="U-BOT",
        granted_scopes=frozenset(),
        bot_token="xoxb-test",
    )
    count = await backfill_channel(
        db_session,
        FakePrivateSlackClient(),
        workspace,
        "G1",
        oldest=None,
        latest=None,
        limit=200,
    )

    assert count == 0


def test_slack_api_error_classifies_invalid_credentials():
    assert SlackApiError("auth.test", "invalid_auth").credential_invalid is True
    assert SlackApiError("conversations.info", "channel_not_found").credential_invalid is False
