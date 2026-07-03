from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from html import escape
from uuid import uuid4

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Paper,
    SlackChannel,
    SlackMention,
    ZoteroCollectionSync,
    ZoteroItemSync,
    utcnow,
)


BOT_NOTE_TITLE = "Bot notes"


@dataclass(frozen=True)
class ZoteroSettings:
    api_key: str
    group_id: str
    api_base_url: str


class ZoteroApiError(RuntimeError):
    pass


class ZoteroApiClient:
    def __init__(self, settings: ZoteroSettings):
        self.settings = settings
        self.prefix = f"/groups/{settings.group_id}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        request_headers = {
            "Zotero-API-Key": self.settings.api_key,
            "Zotero-API-Version": "3",
        }
        if json is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)
        async with httpx.AsyncClient(base_url=self.settings.api_base_url, timeout=20) as client:
            response = await client.request(
                method,
                path,
                json=json,
                params=params,
                headers=request_headers,
            )
        if response.status_code >= 400:
            raise ZoteroApiError(f"Zotero API {method} {path} failed: {response.status_code}")
        return response

    async def create_collection(self, name: str) -> str:
        response = await self.request(
            "POST",
            f"{self.prefix}/collections",
            json=[{"name": name}],
            headers={"Zotero-Write-Token": _write_token()},
        )
        return _created_key(response.json(), 0)

    async def find_item_by_extra_marker(self, marker: str) -> str | None:
        response = await self.request(
            "GET",
            f"{self.prefix}/items",
            params={"format": "json", "q": marker, "qmode": "everything"},
        )
        for item in response.json():
            data = item.get("data") or {}
            if data.get("itemType") == "note":
                continue
            if marker in (data.get("extra") or ""):
                return data.get("key") or item.get("key")
        return None

    async def find_child_note_by_title(self, item_key: str, title: str) -> str | None:
        response = await self.request("GET", f"{self.prefix}/items/{item_key}/children")
        for item in response.json():
            data = item.get("data") or {}
            if data.get("itemType") != "note":
                continue
            if title in (data.get("note") or ""):
                return data.get("key") or item.get("key")
        return None

    async def create_item(self, payload: dict) -> str:
        response = await self.request(
            "POST",
            f"{self.prefix}/items",
            json=[payload],
            headers={"Zotero-Write-Token": _write_token()},
        )
        return _created_key(response.json(), 0)

    async def get_item_data(self, item_key: str) -> dict:
        response = await self.request("GET", f"{self.prefix}/items/{item_key}")
        data = response.json().get("data")
        if not isinstance(data, dict):
            raise ZoteroApiError(f"Zotero item {item_key} returned no editable data")
        return data

    async def patch_item(self, item_key: str, payload: dict, *, version: int | None) -> None:
        headers = {}
        if version is not None:
            headers["If-Unmodified-Since-Version"] = str(version)
        await self.request("PATCH", f"{self.prefix}/items/{item_key}", json=payload, headers=headers)

    async def ensure_item_collections(self, item_key: str, collection_keys: list[str]) -> None:
        data = await self.get_item_data(item_key)
        existing = set(data.get("collections") or [])
        desired = sorted(existing.union(collection_keys))
        if desired == sorted(existing):
            return
        await self.patch_item(item_key, {"collections": desired}, version=data.get("version"))

    async def create_child_note(self, parent_item_key: str, note_html: str) -> str:
        response = await self.request(
            "POST",
            f"{self.prefix}/items",
            json=[
                {
                    "itemType": "note",
                    "parentItem": parent_item_key,
                    "note": note_html,
                }
            ],
            headers={"Zotero-Write-Token": _write_token()},
        )
        return _created_key(response.json(), 0)

    async def update_note(self, note_key: str, note_html: str) -> None:
        data = await self.get_item_data(note_key)
        if data.get("note") == note_html:
            return
        await self.patch_item(note_key, {"note": note_html}, version=data.get("version"))


async def sync_ready_papers_to_zotero(
    db: Session,
    *,
    client: ZoteroApiClient | None = None,
    limit: int | None = None,
) -> int:
    settings = _zotero_settings()
    if settings is None and client is None:
        return 0
    client = client or ZoteroApiClient(settings)  # type: ignore[arg-type]
    candidates = _sync_candidates(db, limit=limit or get_settings().zotero_sync_limit)
    synced = 0
    for paper in candidates:
        if await sync_paper_to_zotero(db, paper, client):
            synced += 1
    db.commit()
    return synced


def sync_ready_papers_to_zotero_sync(
    db: Session,
    *,
    client: ZoteroApiClient | None = None,
    limit: int | None = None,
) -> int:
    return asyncio.run(sync_ready_papers_to_zotero(db, client=client, limit=limit))


async def sync_paper_to_zotero(db: Session, paper: Paper, client: ZoteroApiClient) -> bool:
    item_sync = db.get(ZoteroItemSync, paper.id)
    if item_sync is None:
        item_sync = ZoteroItemSync(paper_id=paper.id)
        db.add(item_sync)
        db.flush()

    item_sync.sync_attempts += 1
    try:
        mentions = _public_mentions(db, paper.id)
        if not mentions:
            item_sync.sync_status = "skipped"
            item_sync.sync_error = "No public Slack mentions available for Zotero sync"
            item_sync.last_synced_at = utcnow()
            return False

        collection_keys = []
        for mention, channel in mentions:
            collection_keys.append(await _ensure_channel_collection(db, channel, client))

        marker = _source_marker(paper)
        if not item_sync.zotero_item_key:
            existing_key = await client.find_item_by_extra_marker(marker)
            if existing_key:
                item_sync.zotero_item_key = existing_key
                await client.ensure_item_collections(
                    item_sync.zotero_item_key,
                    sorted(set(collection_keys)),
                )
            else:
                item_sync.zotero_item_key = await client.create_item(
                    _zotero_item_payload(paper, sorted(set(collection_keys)), marker)
                )
        else:
            await client.ensure_item_collections(item_sync.zotero_item_key, sorted(set(collection_keys)))

        note_html = render_bot_note(paper, [mention for mention, _channel in mentions])
        if not item_sync.zotero_note_key:
            item_sync.zotero_note_key = await client.find_child_note_by_title(
                item_sync.zotero_item_key,
                BOT_NOTE_TITLE,
            )
        if item_sync.zotero_note_key:
            await client.update_note(item_sync.zotero_note_key, note_html)
        else:
            item_sync.zotero_note_key = await client.create_child_note(
                item_sync.zotero_item_key,
                note_html,
            )

        item_sync.sync_status = "synced"
        item_sync.sync_error = None
        item_sync.next_sync_retry_at = None
        item_sync.last_synced_at = utcnow()
        return True
    except Exception as exc:
        item_sync.sync_status = "failed"
        item_sync.sync_error = str(exc)
        delay_minutes = min(60 * 24, 2 ** min(item_sync.sync_attempts, 8))
        item_sync.next_sync_retry_at = utcnow() + timedelta(minutes=delay_minutes)
        return False


def render_bot_note(paper: Paper, mentions: list[SlackMention]) -> str:
    rows = []
    for mention in sorted(mentions, key=lambda item: item.posted_at or item.created_at, reverse=True):
        channel = f"#{mention.channel_name}"
        user = mention.user_name or mention.user_id or "Unknown user"
        date = (mention.posted_at or mention.created_at).date().isoformat()
        permalink = mention.slack_permalink
        source_url = mention.original_url
        if permalink:
            message_link = f'<a href="{escape(permalink)}">Slack message</a>'
        else:
            message_link = "Slack message unavailable"
        rows.append(
            "<li>"
            f"<strong>{escape(channel)}</strong> - {escape(user)} - {escape(date)} - "
            f'{message_link} - <a href="{escape(source_url)}">shared link</a>'
            "</li>"
        )

    title = escape(paper.title or f"{paper.source_type}:{paper.source_id}")
    return (
        f"<h1>{BOT_NOTE_TITLE}</h1>"
        f"<p>Bot-generated note for <em>{title}</em>.</p>"
        "<h2>Slack shares</h2>"
        f"<ul>{''.join(rows)}</ul>"
    )


def _sync_candidates(db: Session, *, limit: int) -> list[Paper]:
    now = utcnow()
    return list(
        db.scalars(
            select(Paper)
            .outerjoin(ZoteroItemSync, ZoteroItemSync.paper_id == Paper.id)
            .where(
                Paper.metadata_status == "ready",
                or_(
                    ZoteroItemSync.paper_id.is_(None),
                    ZoteroItemSync.last_synced_at.is_(None),
                    ZoteroItemSync.next_sync_retry_at <= now,
                    Paper.last_seen_at > ZoteroItemSync.last_synced_at,
                ),
            )
            .order_by(Paper.last_seen_at.asc())
            .limit(limit)
        )
    )


def _public_mentions(db: Session, paper_id: str) -> list[tuple[SlackMention, SlackChannel]]:
    return list(
        db.execute(
            select(SlackMention, SlackChannel)
            .join(SlackChannel, SlackChannel.id == SlackMention.channel_id)
            .where(SlackMention.paper_id == paper_id, SlackChannel.is_private.is_(False))
            .order_by(SlackMention.posted_at.desc())
        ).all()
    )


async def _ensure_channel_collection(
    db: Session,
    channel: SlackChannel,
    client: ZoteroApiClient,
) -> str:
    sync = db.get(ZoteroCollectionSync, channel.id)
    if sync and sync.zotero_collection_key:
        return sync.zotero_collection_key
    if sync is None:
        sync = ZoteroCollectionSync(channel_id=channel.id)
        db.add(sync)
        db.flush()

    sync.zotero_collection_key = await client.create_collection(channel.name)
    sync.sync_status = "synced"
    sync.sync_error = None
    sync.last_synced_at = utcnow()
    return sync.zotero_collection_key


def _zotero_item_payload(paper: Paper, collection_keys: list[str], marker: str) -> dict:
    extra = [marker]
    if paper.source_type == "arxiv":
        extra.append(f"arXiv: {paper.source_id}")
    if paper.primary_category:
        extra.append(f"Primary category: {paper.primary_category}")
    return {
        "itemType": "journalArticle",
        "title": paper.title or f"{paper.source_type}:{paper.source_id}",
        "creators": _creators(paper.authors),
        "abstractNote": paper.abstract or "",
        "publicationTitle": "arXiv" if paper.source_type == "arxiv" else "",
        "DOI": paper.source_id if paper.source_type == "doi" else "",
        "date": _date_string(paper),
        "url": paper.canonical_url or paper.pdf_url or "",
        "collections": collection_keys,
        "extra": "\n".join(extra),
    }


def _creators(authors: str | None) -> list[dict]:
    if not authors:
        return []
    return [
        {"creatorType": "author", "name": author.strip()}
        for author in authors.splitlines()
        if author.strip()
    ]


def _date_string(paper: Paper) -> str:
    if paper.published_at:
        return paper.published_at.date().isoformat()
    if paper.updated_at:
        return paper.updated_at.date().isoformat()
    return ""


def _source_marker(paper: Paper) -> str:
    return f"Slack Paper Archive: {paper.source_type}:{paper.source_id}"


def _created_key(payload: dict, index: int) -> str:
    value = (payload.get("success") or payload.get("successful") or {}).get(str(index))
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("key"):
        return value["key"]
    failed = (payload.get("failed") or {}).get(str(index))
    if failed:
        raise ZoteroApiError(f"Zotero object creation failed: {failed}")
    raise ZoteroApiError(f"Zotero response did not include created object key: {payload}")


def _write_token() -> str:
    return uuid4().hex


def _zotero_settings() -> ZoteroSettings | None:
    settings = get_settings()
    if not settings.zotero_api_key or not settings.zotero_group_id:
        return None
    return ZoteroSettings(
        api_key=settings.zotero_api_key,
        group_id=settings.zotero_group_id,
        api_base_url=settings.zotero_api_base_url.rstrip("/"),
    )
