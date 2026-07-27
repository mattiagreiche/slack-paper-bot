from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote, quote_plus

import httpx
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Paper,
    RelatedPaperRun,
    RelatedPaperSuggestion,
    SlackChannel,
    SlackInstallation,
    SlackMention,
    ZoteroItemSync,
    utcnow,
)


PROVIDER = "semantic_scholar"
RECOMMENDATION_FIELDS = ",".join(
    [
        "title",
        "url",
        "authors",
        "year",
        "abstract",
        "venue",
        "externalIds",
        "citationCount",
        "fieldsOfStudy",
        "publicationTypes",
        "publicationDate",
        "openAccessPdf",
    ]
)


class RelatedPaperError(RuntimeError):
    pass


class RelatedPaperUnavailable(RelatedPaperError):
    pass


@dataclass(frozen=True)
class RelatedPaper:
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    publication_date: str | None
    venue: str | None
    url: str | None
    abstract: str | None
    external_ids: dict
    citation_count: int | None
    fields_of_study: list[str]
    publication_types: list[str]


class SemanticScholarRecommendationsClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.semanticscholar.org",
        recommendation_pool: str = "recent",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.recommendation_pool = recommendation_pool

    async def recommendations_for_paper(self, paper_id: str, *, limit: int) -> list[RelatedPaper]:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
            response = await client.get(
                f"/recommendations/v1/papers/forpaper/{quote(paper_id, safe=':')}",
                params={
                    "limit": limit,
                    "from": self.recommendation_pool,
                    "fields": RECOMMENDATION_FIELDS,
                },
                headers=headers,
            )
        if response.status_code == 404:
            raise RelatedPaperUnavailable("Source paper was not found by Semantic Scholar")
        if response.status_code == 400:
            raise RelatedPaperUnavailable("Source paper is not usable for recommendations")
        if response.status_code == 429:
            raise RelatedPaperError("Semantic Scholar recommendation API was rate-limited")
        response.raise_for_status()
        payload = response.json()
        return parse_recommendations(payload)


def parse_recommendations(payload: dict) -> list[RelatedPaper]:
    papers = payload.get("recommendedPapers")
    if not isinstance(papers, list):
        raise RelatedPaperError("Semantic Scholar response did not include recommendedPapers")
    return [paper for item in papers if (paper := _parse_recommended_paper(item)) is not None]


def query_id_for_paper(paper: Paper) -> str | None:
    if paper.source_type == "semantic_scholar":
        return paper.source_id
    if paper.source_type == "arxiv":
        return f"ArXiv:{paper.source_id}"
    if paper.source_type == "doi":
        return f"DOI:{paper.source_id}"
    return None


def ensure_related_run(
    db: Session,
    paper: Paper,
    *,
    team_id: str | None = None,
) -> RelatedPaperRun | None:
    if not get_settings().related_papers_enabled:
        return None
    if not _has_public_mentions(db, paper.id, team_id=team_id):
        return None
    query_id = query_id_for_paper(paper)
    if not query_id:
        return None
    run = db.get(RelatedPaperRun, paper.id)
    if run is None:
        run = RelatedPaperRun(paper_id=paper.id, provider=PROVIDER)
        db.add(run)
        db.flush()
    run.query_id = query_id
    return run


async def refresh_pending_related_papers(
    db: Session,
    *,
    client: SemanticScholarRecommendationsClient | None = None,
    limit: int | None = None,
    team_id: str | None = None,
) -> int:
    settings = get_settings()
    if not settings.related_papers_enabled and client is None:
        return 0

    resolved_team_id = team_id or _active_team_id(db)
    if client is None and resolved_team_id is None:
        return 0

    _ensure_runs_for_synced_papers(db, team_id=resolved_team_id)
    client = client or SemanticScholarRecommendationsClient(
        api_key=settings.semantic_scholar_api_key,
        base_url=settings.semantic_scholar_api_base_url,
        recommendation_pool=settings.semantic_scholar_recommendation_pool,
    )
    refreshed = 0
    for run in _pending_runs(
        db,
        limit=limit or settings.zotero_sync_limit,
        team_id=resolved_team_id,
    ):
        paper = db.get(Paper, run.paper_id)
        if paper is None:
            continue
        if await refresh_related_papers_for_run(db, run, paper, client=client):
            refreshed += 1
    db.commit()
    return refreshed


def refresh_pending_related_papers_sync(
    db: Session,
    *,
    client: SemanticScholarRecommendationsClient | None = None,
    limit: int | None = None,
    team_id: str | None = None,
) -> int:
    return asyncio.run(
        refresh_pending_related_papers(
            db,
            client=client,
            limit=limit,
            team_id=team_id,
        )
    )


async def refresh_related_papers_for_run(
    db: Session,
    run: RelatedPaperRun,
    paper: Paper,
    *,
    client: SemanticScholarRecommendationsClient,
) -> bool:
    query_id = run.query_id or query_id_for_paper(paper)
    if not query_id:
        run.status = "unavailable"
        run.error = "No Semantic Scholar recommendation identifier is available"
        run.last_fetched_at = utcnow()
        run.changed_since_zotero_sync = True
        return True

    run.query_id = query_id
    run.attempts += 1
    try:
        suggestions = await client.recommendations_for_paper(
            query_id,
            limit=get_settings().related_papers_limit + 1,
        )
        suggestions = _without_self_recommendations(paper, suggestions)
        _store_suggestions(db, run, suggestions[: get_settings().related_papers_limit])
        run.status = "ready" if suggestions else "unavailable"
        run.error = None if suggestions else "No related papers were returned by Semantic Scholar"
        run.next_retry_at = None
        run.last_fetched_at = utcnow()
        run.changed_since_zotero_sync = True
        return True
    except RelatedPaperUnavailable as exc:
        _clear_suggestions(db, run)
        run.status = "unavailable"
        run.error = str(exc)
        run.next_retry_at = None
        run.last_fetched_at = utcnow()
        run.changed_since_zotero_sync = True
        return True
    except Exception as exc:  # noqa: BLE001 - external dependency failures are stored.
        run.status = "failed"
        run.error = str(exc)
        delay_minutes = min(60 * 24, 2 ** min(run.attempts, 8))
        run.next_retry_at = utcnow() + timedelta(minutes=delay_minutes)
        run.last_fetched_at = utcnow()
        run.changed_since_zotero_sync = True
        return True


def related_suggestions_for_paper(db: Session, paper_id: str) -> list[RelatedPaperSuggestion]:
    return list(
        db.scalars(
            select(RelatedPaperSuggestion)
            .where(
                RelatedPaperSuggestion.paper_id == paper_id,
                RelatedPaperSuggestion.provider == PROVIDER,
            )
            .order_by(RelatedPaperSuggestion.rank.asc())
        )
    )


def semantic_scholar_source_url(paper: Paper) -> str:
    if paper.source_type == "semantic_scholar":
        return f"https://www.semanticscholar.org/paper/{quote(paper.source_id, safe='')}"
    query = paper.title or f"{paper.source_type}:{paper.source_id}"
    return f"https://www.semanticscholar.org/search?q={quote_plus(query)}&sort=relevance"


def retry_related_papers(
    db: Session,
    paper_id: str,
    *,
    team_id: str | None = None,
) -> Paper | None:
    paper = db.get(Paper, paper_id)
    if paper is None:
        return None
    if team_id is not None and not _has_public_mentions(db, paper.id, team_id=team_id):
        return None
    run = db.get(RelatedPaperRun, paper.id)
    if run is None:
        run = RelatedPaperRun(paper_id=paper.id, provider=PROVIDER)
        db.add(run)
        db.flush()
    run.query_id = query_id_for_paper(paper)
    run.status = "pending"
    run.error = None
    run.next_retry_at = None
    db.commit()
    return paper


def mark_related_note_synced(db: Session, paper_id: str) -> None:
    run = db.get(RelatedPaperRun, paper_id)
    if run is not None:
        run.changed_since_zotero_sync = False


def _ensure_runs_for_synced_papers(
    db: Session,
    *,
    team_id: str | None = None,
) -> None:
    conditions = [
        ZoteroItemSync.sync_status == "synced",
        ~exists().where(RelatedPaperRun.paper_id == Paper.id),
    ]
    if team_id is not None:
        conditions.append(_eligible_public_mention_exists(team_id))
    for paper in db.scalars(
        select(Paper)
        .join(ZoteroItemSync, ZoteroItemSync.paper_id == Paper.id)
        .where(*conditions)
    ):
        ensure_related_run(db, paper, team_id=team_id)


def _pending_runs(
    db: Session,
    *,
    limit: int,
    team_id: str | None = None,
) -> list[RelatedPaperRun]:
    now = utcnow()
    conditions = [
        RelatedPaperRun.provider == PROVIDER,
        or_(
            RelatedPaperRun.status == "pending",
            RelatedPaperRun.next_retry_at <= now,
        ),
    ]
    if team_id is not None:
        conditions.append(_eligible_public_mention_exists(team_id))
    return list(
        db.scalars(
            select(RelatedPaperRun)
            .join(Paper, Paper.id == RelatedPaperRun.paper_id)
            .where(*conditions)
            .order_by(RelatedPaperRun.created_at.asc())
            .limit(limit)
        )
    )


def _has_public_mentions(
    db: Session,
    paper_id: str,
    *,
    team_id: str | None = None,
) -> bool:
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
    return bool(
        db.scalar(
            select(SlackMention.id)
            .join(SlackChannel, SlackChannel.id == SlackMention.channel_id)
            .where(*conditions)
            .limit(1)
        )
    )


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
    if installation is None or not installation.is_active:
        return None
    return installation.team_id


def _store_suggestions(
    db: Session,
    run: RelatedPaperRun,
    suggestions: list[RelatedPaper],
) -> None:
    existing = {
        suggestion.suggested_paper_id: suggestion
        for suggestion in db.scalars(
            select(RelatedPaperSuggestion).where(
                RelatedPaperSuggestion.paper_id == run.paper_id,
                RelatedPaperSuggestion.provider == PROVIDER,
            )
        )
    }
    keep_ids = set()
    for rank, paper in enumerate(suggestions, start=1):
        keep_ids.add(paper.paper_id)
        row = existing.get(paper.paper_id)
        if row is None:
            row = RelatedPaperSuggestion(
                paper_id=run.paper_id,
                provider=PROVIDER,
                suggested_paper_id=paper.paper_id,
                rank=rank,
                title=paper.title,
            )
            db.add(row)
        row.rank = rank
        row.title = paper.title
        row.authors = "\n".join(paper.authors) if paper.authors else None
        row.year = paper.year
        row.publication_date = paper.publication_date
        row.venue = paper.venue
        row.url = paper.url
        row.abstract = paper.abstract
        row.external_ids = json.dumps(paper.external_ids, sort_keys=True) if paper.external_ids else None
        row.citation_count = paper.citation_count
        row.fields_of_study = "\n".join(paper.fields_of_study) if paper.fields_of_study else None
        row.publication_types = "\n".join(paper.publication_types) if paper.publication_types else None

    for paper_id, row in existing.items():
        if paper_id not in keep_ids:
            db.delete(row)


def _clear_suggestions(db: Session, run: RelatedPaperRun) -> None:
    for suggestion in related_suggestions_for_paper(db, run.paper_id):
        db.delete(suggestion)


def _without_self_recommendations(
    paper: Paper,
    suggestions: list[RelatedPaper],
) -> list[RelatedPaper]:
    return [suggestion for suggestion in suggestions if not _is_same_paper(paper, suggestion)]


def _is_same_paper(paper: Paper, suggestion: RelatedPaper) -> bool:
    if paper.source_type == "semantic_scholar" and suggestion.paper_id == paper.source_id:
        return True
    external_ids = {str(key).lower(): str(value).lower() for key, value in suggestion.external_ids.items()}
    if paper.source_type == "arxiv" and external_ids.get("arxiv") == paper.source_id.lower():
        return True
    if paper.source_type == "doi" and external_ids.get("doi") == paper.source_id.lower():
        return True
    return False


def _parse_recommended_paper(item: object) -> RelatedPaper | None:
    if not isinstance(item, dict):
        return None
    paper_id = item.get("paperId")
    title = item.get("title")
    if not paper_id or not title:
        return None
    return RelatedPaper(
        paper_id=str(paper_id),
        title=_clean_text(str(title)),
        authors=[
            str(author.get("name"))
            for author in item.get("authors") or []
            if isinstance(author, dict) and author.get("name")
        ],
        year=int(item["year"]) if item.get("year") else None,
        publication_date=str(item["publicationDate"]) if item.get("publicationDate") else None,
        venue=_clean_text(str(item["venue"])) if item.get("venue") else None,
        url=str(item["url"]) if item.get("url") else None,
        abstract=_clean_text(str(item["abstract"])) if item.get("abstract") else None,
        external_ids=item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {},
        citation_count=int(item["citationCount"]) if item.get("citationCount") is not None else None,
        fields_of_study=[str(value) for value in item.get("fieldsOfStudy") or [] if value],
        publication_types=[str(value) for value in item.get("publicationTypes") or [] if value],
    )


def _clean_text(value: str) -> str:
    return " ".join(value.split())
