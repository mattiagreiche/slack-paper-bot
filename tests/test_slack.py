import time

import pytest

from app.config import Settings
from app.services.slack import (
    SlackSignatureError,
    enrich_slack_message,
    joined_channels,
    slack_message_from_event,
    verify_slack_signature,
)


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
        return {"id": channel_id, "name": "papers", "is_private": False}

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
    async def conversations(self, *, types="public_channel,private_channel", limit=200):
        return [
            {"id": "C1", "name": "joined", "is_member": True},
            {"id": "C2", "name": "not-joined", "is_member": False},
        ]


@pytest.mark.asyncio
async def test_joined_channels_filters_to_membership():
    channels = await joined_channels(FakeListSlackClient())

    assert [channel["id"] for channel in channels] == ["C1"]
