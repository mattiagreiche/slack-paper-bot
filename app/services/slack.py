import hashlib
import hmac
import time
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.models import SlackChannel
from app.services.ingestion import SlackMessage, ingest_slack_message


class SlackSignatureError(ValueError):
    pass


def verify_slack_signature(
    *,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    settings: Settings,
) -> None:
    if not settings.slack_signing_secret:
        raise SlackSignatureError("SLACK_SIGNING_SECRET is not configured")
    if not timestamp or not signature:
        raise SlackSignatureError("missing Slack signature headers")
    if abs(time.time() - int(timestamp)) > settings.slack_request_tolerance_seconds:
        raise SlackSignatureError("stale Slack request timestamp")

    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(
        settings.slack_signing_secret.encode(),
        base,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise SlackSignatureError("invalid Slack signature")


def slack_message_from_event(event: dict, team_id: str | None) -> SlackMessage | None:
    if event.get("type") != "message":
        return None
    if event.get("channel_type") not in {"channel", "group"}:
        return None
    if event.get("subtype") in {"message_deleted", "bot_message"}:
        return None

    payload = event.get("message", event)
    text = payload.get("text", "")
    if not text:
        return None

    channel_id = event.get("channel") or payload.get("channel")
    message_ts = payload.get("ts") or event.get("ts")
    if not channel_id or not message_ts:
        return None

    channel_type = event.get("channel_type")
    return SlackMessage(
        team_id=team_id,
        channel_id=channel_id,
        channel_name=event.get("channel_name") or channel_id,
        channel_is_private=channel_type == "group",
        user_id=payload.get("user") or event.get("user"),
        user_name=None,
        message_ts=message_ts,
        thread_ts=payload.get("thread_ts") or event.get("thread_ts"),
        text=text,
        permalink=None,
    )


@dataclass
class SlackApiClient:
    token: str

    async def api(self, method: str, **params) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"https://slack.com/api/{method}",
                headers={"Authorization": f"Bearer {self.token}"},
                data=params,
            )
            response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API {method} failed: {data.get('error', 'unknown_error')}")
        return data

    async def conversation_info(self, channel_id: str) -> dict:
        return (await self.api("conversations.info", channel=channel_id))["channel"]

    async def user_info(self, user_id: str) -> dict:
        return (await self.api("users.info", user=user_id))["user"]

    async def conversations(
        self,
        *,
        types: str = "public_channel,private_channel",
        limit: int = 200,
    ) -> list[dict]:
        channels: list[dict] = []
        cursor: str | None = None
        while True:
            params = {"types": types, "limit": limit, "exclude_archived": "true"}
            if cursor:
                params["cursor"] = cursor
            data = await self.api("conversations.list", **params)
            channels.extend(data.get("channels", []))
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return channels

    async def history(
        self,
        channel_id: str,
        *,
        oldest: str | None = None,
        latest: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        params = {"channel": channel_id, "limit": limit}
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest
        data = await self.api("conversations.history", **params)
        return data.get("messages", [])

    async def replies(self, channel_id: str, thread_ts: str) -> list[dict]:
        data = await self.api("conversations.replies", channel=channel_id, ts=thread_ts)
        return data.get("messages", [])

    async def permalink(self, channel_id: str, message_ts: str) -> str | None:
        data = await self.api("chat.getPermalink", channel=channel_id, message_ts=message_ts)
        return data.get("permalink")


async def enrich_slack_message(message: SlackMessage, client: SlackApiClient | None) -> SlackMessage:
    if client is None:
        return message

    channel_name = message.channel_name
    channel_is_private = message.channel_is_private
    user_name = message.user_name
    permalink = message.permalink

    try:
        channel = await client.conversation_info(message.channel_id)
        channel_name = channel.get("name") or channel_name
        channel_is_private = bool(channel.get("is_private"))
    except Exception:
        pass

    if message.user_id:
        try:
            user = await client.user_info(message.user_id)
            profile = user.get("profile") or {}
            user_name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("real_name")
                or user.get("name")
                or user_name
            )
        except Exception as exc:
            print(f"Slack user lookup failed for {message.user_id}: {exc}", flush=True)
            pass

    try:
        permalink = await client.permalink(message.channel_id, message.message_ts)
    except Exception:
        pass

    return SlackMessage(
        team_id=message.team_id,
        channel_id=message.channel_id,
        channel_name=channel_name,
        channel_is_private=channel_is_private,
        user_id=message.user_id,
        user_name=user_name,
        message_ts=message.message_ts,
        thread_ts=message.thread_ts,
        text=message.text,
        permalink=permalink,
    )


async def backfill_channel(
    db,
    client: SlackApiClient,
    channel_id: str,
    *,
    oldest: str | None,
    latest: str | None = None,
    limit: int,
) -> int:
    channel = await client.conversation_info(channel_id)
    messages = await client.history(channel_id, oldest=oldest, latest=latest, limit=limit)
    count = 0
    latest_ts = oldest
    for raw in reversed(messages):
        if raw.get("subtype") in {"message_deleted", "bot_message"}:
            continue
        ts = raw.get("ts")
        if not ts:
            continue
        latest_ts = max(latest_ts or ts, ts)
        permalink = None
        try:
            permalink = await client.permalink(channel_id, ts)
        except Exception:  # noqa: BLE001 - permalink is helpful but not required.
            permalink = None
        msg = SlackMessage(
            team_id=None,
            channel_id=channel_id,
            channel_name=channel.get("name") or channel_id,
            channel_is_private=bool(channel.get("is_private")),
            user_id=raw.get("user"),
            user_name=None,
            message_ts=ts,
            thread_ts=raw.get("thread_ts"),
            text=raw.get("text", ""),
            permalink=permalink,
        )
        msg = await enrich_slack_message(msg, client)
        count += ingest_slack_message(db, msg, event_key=f"backfill:{channel_id}:{ts}", commit=False)

        if raw.get("reply_count", 0) > 0:
            for reply in await client.replies(channel_id, ts):
                reply_ts = reply.get("ts")
                if not reply_ts or reply_ts == ts:
                    continue
                reply_msg = SlackMessage(
                    team_id=None,
                    channel_id=channel_id,
                    channel_name=channel.get("name") or channel_id,
                    channel_is_private=bool(channel.get("is_private")),
                    user_id=reply.get("user"),
                    user_name=None,
                    message_ts=reply_ts,
                    thread_ts=ts,
                    text=reply.get("text", ""),
                    permalink=permalink,
                )
                reply_msg = await enrich_slack_message(reply_msg, client)
                count += ingest_slack_message(
                    db,
                    reply_msg,
                    event_key=f"backfill:{channel_id}:{reply_ts}",
                    commit=False,
                )
    stored_channel = db.get(SlackChannel, channel_id)
    if stored_channel and latest_ts:
        stored_channel.last_catchup_ts = latest_ts
        if oldest is None:
            stored_channel.last_backfilled_ts = latest_ts
    db.commit()
    return count


async def joined_channels(client: SlackApiClient) -> list[dict]:
    channels = await client.conversations(types="public_channel,private_channel")
    return [channel for channel in channels if channel.get("is_member")]
