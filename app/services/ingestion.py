import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.extractors import extractor_for_url
from app.models import IngestionEvent, Paper, SlackChannel, SlackMention, SlackUser, utcnow

URL_RE = re.compile(r"<(https?://[^>|]+)(?:\|[^>]+)?>|(https?://[^\s<>\)]+)")


@dataclass(frozen=True)
class SlackMessage:
    team_id: str | None
    channel_id: str
    channel_name: str
    channel_is_private: bool
    user_id: str | None
    user_name: str | None
    message_ts: str
    thread_ts: str | None
    text: str
    permalink: str | None = None


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(text or ""):
        url = match.group(1) or match.group(2)
        url = url.rstrip(".,;")
        if url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def ingest_slack_message(
    db: Session,
    message: SlackMessage,
    *,
    event_key: str | None = None,
    commit: bool = True,
) -> int:
    if event_key and db.get(IngestionEvent, event_key):
        return 0

    _upsert_channel(db, message)
    if message.user_id:
        _upsert_user(db, message.user_id, message.user_name)

    ingested = 0
    for url in extract_urls(message.text):
        extractor = extractor_for_url(url)
        if extractor is None:
            continue

        source_key = extractor.normalize(url)
        paper = db.scalar(
            select(Paper).where(
                Paper.source_type == source_key.source_type,
                Paper.source_id == source_key.source_id,
            )
        )
        if paper is None:
            paper = Paper(
                source_type=source_key.source_type,
                source_id=source_key.source_id,
                canonical_url=source_key.canonical_url,
                pdf_url=source_key.pdf_url,
                metadata_status="pending",
                last_seen_at=utcnow(),
            )
            db.add(paper)
            db.flush()
        else:
            paper.last_seen_at = utcnow()
            if not paper.canonical_url:
                paper.canonical_url = source_key.canonical_url
            if not paper.pdf_url:
                paper.pdf_url = source_key.pdf_url

        exists = db.scalar(
            select(SlackMention).where(
                SlackMention.channel_id == message.channel_id,
                SlackMention.message_ts == message.message_ts,
                SlackMention.paper_id == paper.id,
            )
        )
        if exists:
            exists.team_id = message.team_id or exists.team_id
            exists.channel_name = message.channel_name
            exists.user_name = message.user_name or exists.user_name
            exists.slack_permalink = message.permalink or exists.slack_permalink
            continue

        db.add(
            SlackMention(
                paper_id=paper.id,
                team_id=message.team_id,
                channel_id=message.channel_id,
                channel_name=message.channel_name,
                user_id=message.user_id,
                user_name=message.user_name,
                message_ts=message.message_ts,
                thread_ts=message.thread_ts,
                original_url=url,
                slack_permalink=message.permalink,
                posted_at=slack_ts_to_datetime(message.message_ts),
            )
        )
        ingested += 1

    if event_key:
        db.add(IngestionEvent(key=event_key, source="slack", status="processed"))

    if commit:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return 0
    return ingested


def _upsert_channel(db: Session, message: SlackMessage) -> None:
    channel = db.get(SlackChannel, message.channel_id)
    if channel is None:
        channel = next(
            (
                obj
                for obj in db.new
                if isinstance(obj, SlackChannel) and obj.id == message.channel_id
            ),
            None,
        )
    if channel is None:
        db.add(
            SlackChannel(
                id=message.channel_id,
                name=message.channel_name,
                is_private=message.channel_is_private,
            )
        )
    else:
        channel.name = message.channel_name
        channel.is_private = message.channel_is_private


def _upsert_user(db: Session, user_id: str, user_name: str | None) -> None:
    user = db.get(SlackUser, user_id)
    if user is None:
        user = next(
            (obj for obj in db.new if isinstance(obj, SlackUser) and obj.id == user_id),
            None,
        )
    if user is None:
        db.add(SlackUser(id=user_id, display_name=user_name, real_name=user_name))
    elif user_name:
        user.display_name = user_name
        user.real_name = user.real_name or user_name


def slack_ts_to_datetime(ts: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None
