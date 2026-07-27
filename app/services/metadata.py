import asyncio
import re
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.extractors import SourceKey, extractor_for_source
from app.extractors.base import PaperMetadata
from app.config import get_settings
from app.models import Paper, SlackChannel, SlackMention, utcnow
from app.services.citations import refresh_citation


async def refresh_pending_metadata(
    db: Session,
    *,
    team_id: str | None,
    limit: int = 20,
) -> int:
    if not team_id:
        return 0

    now = utcnow()
    papers = list(
        db.scalars(
            select(Paper)
            .where(
                Paper.metadata_status.in_(["pending", "failed"]),
                or_(Paper.next_metadata_retry_at.is_(None), Paper.next_metadata_retry_at <= now),
                _eligible_public_mention_exists(team_id),
            )
            .order_by(Paper.created_at.asc())
            .limit(limit)
        )
    )

    refreshed = 0
    delay_seconds = get_settings().arxiv_request_delay_seconds
    for index, paper in enumerate(papers):
        extractor = extractor_for_source(paper.source_type)
        if extractor is None:
            paper.metadata_status = "failed"
            paper.metadata_error = f"No extractor registered for {paper.source_type}"
            continue

        paper.metadata_attempts += 1
        try:
            metadata = await extractor.fetch_metadata(
                SourceKey(
                    source_type=paper.source_type,
                    source_id=paper.source_id,
                    canonical_url=paper.canonical_url or "",
                    pdf_url=paper.pdf_url,
                )
            )
            apply_metadata(paper, metadata)
            try:
                await refresh_citation(db, paper)
            except Exception:
                pass
            refreshed += 1
        except Exception as exc:  # noqa: BLE001 - stored for operator visibility.
            paper.metadata_status = "failed"
            paper.metadata_error = _metadata_error_message(exc)
            delay_minutes = min(60 * 24, 2 ** min(paper.metadata_attempts, 8))
            paper.next_metadata_retry_at = utcnow() + timedelta(minutes=delay_minutes)
        if index < len(papers) - 1 and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    db.commit()
    return refreshed


def refresh_pending_metadata_sync(
    db: Session,
    *,
    team_id: str | None,
    limit: int = 20,
) -> int:
    return asyncio.run(refresh_pending_metadata(db, team_id=team_id, limit=limit))


def apply_metadata(paper: Paper, metadata: PaperMetadata) -> None:
    paper.title = metadata.title
    paper.normalized_title = normalize_title(metadata.title)
    paper.authors = "\n".join(metadata.authors)
    paper.abstract = metadata.abstract
    paper.categories = ",".join(metadata.categories)
    paper.primary_category = metadata.primary_category
    paper.published_at = metadata.published_at
    paper.updated_at = metadata.updated_at
    paper.canonical_url = metadata.canonical_url
    paper.pdf_url = metadata.pdf_url
    paper.metadata_status = "ready"
    paper.metadata_error = None
    paper.next_metadata_retry_at = None


def normalize_title(title: str | None) -> str | None:
    if not title:
        return None
    return re.sub(r"\s+", " ", title).strip().lower()


def _metadata_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or type(exc).__name__


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
