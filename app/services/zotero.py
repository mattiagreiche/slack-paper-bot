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
    RelatedPaperRun,
    SlackChannel,
    SlackInstallation,
    SlackMention,
    TrialZoteroDestination,
    ZoteroCollectionSync,
    ZoteroItemSync,
    utcnow,
)
from app.services.credentials import CredentialCipher, CredentialEncryptionError
from app.services.installations import (
    VALID_CREDENTIAL_STATUS,
    get_verified_zotero_context,
)
from app.services.related import (
    ensure_related_run,
    mark_related_note_synced,
    related_suggestions_for_paper,
    semantic_scholar_source_url,
)


BOT_NOTE_TITLE = "Bot notes"


@dataclass(frozen=True)
class ZoteroSettings:
    api_key: str
    group_id: str
    api_base_url: str


class ZoteroApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

    @property
    def is_authentication_error(self) -> bool:
        return self.status_code in {401, 403}


@dataclass(frozen=True)
class ZoteroDestinationVerification:
    verified: bool
    group_name: str | None = None
    error: str | None = None


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
            raise ZoteroApiError(
                f"Zotero API {method} {path} failed: {response.status_code}",
                status_code=response.status_code,
            )
        return response

    async def verify_destination(self) -> str | None:
        key_response = await self.request("GET", "/keys/current")
        key_payload = key_response.json()
        access = key_payload.get("access") if isinstance(key_payload, dict) else None
        groups = access.get("groups") if isinstance(access, dict) else None
        permission = groups.get(self.settings.group_id) if isinstance(groups, dict) else None
        if permission is None and isinstance(groups, dict):
            permission = groups.get("all")
        if not (
            isinstance(permission, dict)
            and permission.get("library") is True
            and permission.get("write") is True
        ):
            raise ZoteroApiError(
                "Zotero key does not grant library write access to the destination"
            )

        response = await self.request("GET", self.prefix)
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ZoteroApiError("Zotero group response did not include destination data")
        name = data.get("name")
        return str(name).strip() if name else None

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

    async def find_bot_note(self, item_key: str) -> str | None:
        response = await self.request("GET", f"{self.prefix}/items/{item_key}/children")
        for item in response.json():
            data = item.get("data") or {}
            if data.get("itemType") != "note":
                continue
            note = (data.get("note") or "").strip()
            if note.startswith(f"<h1>{BOT_NOTE_TITLE}</h1>"):
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
    team_id: str | None = None,
) -> int:
    resolved_team_id = team_id or _active_team_id(db)
    if client is None:
        resolved = _persisted_zotero_settings(db)
        if resolved is None or resolved_team_id is None:
            return 0
        client = ZoteroApiClient(resolved)

    candidates = _sync_candidates(
        db,
        limit=limit or get_settings().zotero_sync_limit,
        team_id=resolved_team_id,
    )
    synced = 0
    for paper in candidates:
        try:
            if await sync_paper_to_zotero(
                db,
                paper,
                client,
                team_id=resolved_team_id,
            ):
                synced += 1
        except ZoteroApiError as exc:
            if not exc.is_authentication_error:
                raise
            invalidate_persisted_zotero_destination(db)
            break
    db.commit()
    return synced


def sync_ready_papers_to_zotero_sync(
    db: Session,
    *,
    client: ZoteroApiClient | None = None,
    limit: int | None = None,
    team_id: str | None = None,
) -> int:
    return asyncio.run(
        sync_ready_papers_to_zotero(
            db,
            client=client,
            limit=limit,
            team_id=team_id,
        )
    )


async def sync_paper_to_zotero(
    db: Session,
    paper: Paper,
    client: ZoteroApiClient,
    *,
    team_id: str | None = None,
) -> bool:
    item_sync = db.get(ZoteroItemSync, paper.id)
    if item_sync is None:
        item_sync = ZoteroItemSync(paper_id=paper.id)
        db.add(item_sync)
        db.flush()

    item_sync.sync_attempts += 1
    try:
        mentions = _public_mentions(db, paper.id, team_id=team_id)
        if not mentions:
            item_sync.sync_status = "skipped"
            item_sync.sync_error = "No public Slack mentions available for Zotero sync"
            item_sync.last_synced_at = utcnow()
            return False

        collection_keys = []
        for mention, channel in mentions:
            collection_keys.append(
                await _ensure_channel_collection(
                    db,
                    channel,
                    client,
                    team_id=team_id,
                )
            )

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

        note_html = render_bot_note(
            paper,
            [mention for mention, _channel in mentions],
            related_run=db.get(RelatedPaperRun, paper.id),
            related_suggestions=related_suggestions_for_paper(db, paper.id),
        )
        if not item_sync.zotero_note_key:
            item_sync.zotero_note_key = await client.find_bot_note(
                item_sync.zotero_item_key
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
        mark_related_note_synced(db, paper.id)
        ensure_related_run(db, paper, team_id=team_id)
        return True
    except ZoteroApiError as exc:
        _record_sync_failure(item_sync, exc)
        if exc.is_authentication_error:
            invalidate_persisted_zotero_destination(db)
            raise
        return False
    except Exception as exc:
        _record_sync_failure(item_sync, exc)
        return False


def render_bot_note(
    paper: Paper,
    mentions: list[SlackMention],
    *,
    related_run: RelatedPaperRun | None = None,
    related_suggestions: list | None = None,
) -> str:
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

    return (
        f"<h1>{BOT_NOTE_TITLE}</h1>"
        f"{_render_related_section(paper, related_run, related_suggestions or [])}"
        "<h2>Slack shares</h2>"
        f"<ul>{''.join(rows)}</ul>"
    )


def _sync_candidates(
    db: Session,
    *,
    limit: int,
    team_id: str | None = None,
) -> list[Paper]:
    now = utcnow()
    conditions = [
        Paper.metadata_status == "ready",
        or_(
            ZoteroItemSync.paper_id.is_(None),
            ZoteroItemSync.last_synced_at.is_(None),
            ZoteroItemSync.next_sync_retry_at <= now,
            Paper.last_seen_at > ZoteroItemSync.last_synced_at,
            RelatedPaperRun.changed_since_zotero_sync.is_(True),
        ),
    ]
    if team_id is not None:
        conditions.append(_eligible_public_mention_exists(team_id))
    return list(
        db.scalars(
            select(Paper)
            .outerjoin(ZoteroItemSync, ZoteroItemSync.paper_id == Paper.id)
            .outerjoin(RelatedPaperRun, RelatedPaperRun.paper_id == Paper.id)
            .where(*conditions)
            .order_by(Paper.last_seen_at.asc())
            .limit(limit)
        )
    )


def _public_mentions(
    db: Session,
    paper_id: str,
    *,
    team_id: str | None = None,
) -> list[tuple[SlackMention, SlackChannel]]:
    conditions = [
        SlackMention.paper_id == paper_id,
        SlackChannel.is_private.is_(False),
    ]
    if team_id is not None:
        conditions.extend(
            [
                SlackMention.team_id == team_id,
                SlackChannel.team_id == team_id,
            ]
        )
    return list(
        db.execute(
            select(SlackMention, SlackChannel)
            .join(SlackChannel, SlackChannel.id == SlackMention.channel_id)
            .where(*conditions)
            .order_by(SlackMention.posted_at.desc())
        ).all()
    )


async def _ensure_channel_collection(
    db: Session,
    channel: SlackChannel,
    client: ZoteroApiClient,
    *,
    team_id: str | None = None,
) -> str:
    if team_id is not None and channel.team_id != team_id:
        raise ValueError("Slack channel does not belong to the active workspace")
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


def _render_related_section(
    paper: Paper,
    related_run: RelatedPaperRun | None,
    suggestions: list,
) -> str:
    if related_run is None:
        return ""
    if related_run.status == "ready" and suggestions:
        rows = []
        for suggestion in suggestions:
            title = escape(suggestion.title)
            authors = _compact_authors(suggestion.authors)
            year = str(suggestion.year or suggestion.publication_date or "").strip()
            venue = suggestion.venue or ""
            metadata = " - ".join(escape(value) for value in [authors, year, venue] if value)
            link = suggestion.url or _semantic_scholar_url(suggestion.suggested_paper_id)
            identifiers = _compact_identifiers(suggestion.external_ids)
            detail = " ".join(value for value in [metadata, identifiers] if value)
            if detail:
                detail = f"<br><span>{detail}</span>"
            rows.append(f'<li><a href="{escape(link)}">{title}</a>{detail}</li>')
        return (
            "<h2>Related papers (bot-generated via Semantic Scholar)</h2>"
            f"<ol>{''.join(rows)}</ol>"
            f'<p><a href="{escape(semantic_scholar_source_url(paper))}">'
            "View this paper on Semantic Scholar</a> for more discovery options.</p>"
        )
    if related_run.status in {"failed", "unavailable"}:
        return (
            "<h2>Related papers (bot-generated via Semantic Scholar)</h2>"
            "<p>Related papers unavailable from Semantic Scholar.</p>"
        )
    return ""


def _compact_authors(authors: str | None) -> str:
    if not authors:
        return ""
    values = [author.strip() for author in authors.splitlines() if author.strip()]
    if len(values) <= 2:
        return ", ".join(values)
    return f"{values[0]}, {values[1]}, et al."


def _compact_identifiers(external_ids: str | None) -> str:
    if not external_ids:
        return ""
    try:
        import json

        data = json.loads(external_ids)
    except (TypeError, ValueError):
        return ""
    parts = []
    if data.get("DOI"):
        parts.append(f"DOI: {escape(str(data['DOI']))}")
    if data.get("ArXiv"):
        parts.append(f"arXiv: {escape(str(data['ArXiv']))}")
    return " - ".join(parts)


def _semantic_scholar_url(paper_id: str) -> str:
    return f"https://www.semanticscholar.org/paper/{paper_id}"


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


async def verify_zotero_destination(
    *,
    group_id: str,
    api_key: str,
    api_base_url: str = "https://api.zotero.org",
) -> ZoteroDestinationVerification:
    if not group_id.strip() or not api_key or not api_base_url.strip():
        return ZoteroDestinationVerification(
            verified=False,
            error="Zotero destination is incomplete",
        )
    client = ZoteroApiClient(
        ZoteroSettings(
            api_key=api_key,
            group_id=group_id.strip(),
            api_base_url=api_base_url.strip().rstrip("/"),
        )
    )
    try:
        group_name = await client.verify_destination()
    except ZoteroApiError as exc:
        if exc.is_authentication_error:
            error = "Zotero denied access to the group library"
        else:
            error = "Zotero destination verification failed"
        return ZoteroDestinationVerification(verified=False, error=error)
    except (httpx.HTTPError, ValueError):
        return ZoteroDestinationVerification(
            verified=False,
            error="Zotero destination verification failed",
        )
    return ZoteroDestinationVerification(verified=True, group_name=group_name)


def invalidate_persisted_zotero_destination(db: Session) -> None:
    destination = db.get(TrialZoteroDestination, 1)
    if destination is None:
        return
    destination.is_verified = False
    destination.status = "invalid"
    destination.status_code = "access_revoked"
    destination.status_message = "Zotero denied access; destination verification is required"
    destination.last_validated_at = utcnow()


def _record_sync_failure(item_sync: ZoteroItemSync, exc: Exception) -> None:
    item_sync.sync_status = "failed"
    item_sync.sync_error = str(exc)
    delay_minutes = min(60 * 24, 2 ** min(item_sync.sync_attempts, 8))
    item_sync.next_sync_retry_at = utcnow() + timedelta(minutes=delay_minutes)


def _eligible_public_mention_exists(team_id: str):
    return (
        select(SlackMention.id)
        .join(SlackChannel, SlackChannel.id == SlackMention.channel_id)
        .where(
            SlackMention.paper_id == Paper.id,
            SlackMention.team_id == team_id,
            SlackChannel.team_id == team_id,
            SlackChannel.is_private.is_(False),
        )
        .exists()
    )


def _active_team_id(db: Session) -> str | None:
    installation = db.get(SlackInstallation, 1)
    if (
        installation is None
        or not installation.is_active
        or installation.credential_status != VALID_CREDENTIAL_STATUS
    ):
        return None
    return installation.team_id


def _persisted_zotero_settings(db: Session) -> ZoteroSettings | None:
    settings = get_settings()
    try:
        cipher = CredentialCipher(settings.credential_encryption_key)
        destination = get_verified_zotero_context(db, cipher=cipher)
    except CredentialEncryptionError:
        return None
    if destination is None:
        return None
    return ZoteroSettings(
        api_key=destination.api_key,
        group_id=destination.group_id,
        api_base_url=destination.api_base_url.rstrip("/"),
    )
