from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from app.extractors.base import PaperMetadata, SourceKey

SEMANTIC_SCHOLAR_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
SEMANTIC_SCHOLAR_FIELDS = ",".join(
    [
        "paperId",
        "title",
        "abstract",
        "authors",
        "year",
        "publicationDate",
        "venue",
        "externalIds",
        "url",
        "fieldsOfStudy",
        "publicationTypes",
    ]
)


class SemanticScholarExtractor:
    source_type = "semantic_scholar"

    def can_handle(self, url: str) -> bool:
        try:
            self.normalize(url)
        except ValueError:
            return False
        return True

    def normalize(self, url: str) -> SourceKey:
        parsed = urlparse(_strip_slack_wrapping(url))
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if host != "semanticscholar.org":
            raise ValueError("not a Semantic Scholar URL")

        parts = [part for part in parsed.path.split("/") if part]
        if not parts or parts[0] != "paper" or len(parts) < 2:
            raise ValueError("unsupported Semantic Scholar path")
        paper_id = parts[-1]
        if not paper_id or paper_id in {"paper", "search"}:
            raise ValueError("missing Semantic Scholar paper id")

        return SourceKey(
            source_type=self.source_type,
            source_id=paper_id,
            canonical_url=f"https://www.semanticscholar.org/paper/{paper_id}",
            pdf_url=None,
        )

    async def fetch_metadata(self, source_key: SourceKey) -> PaperMetadata:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                SEMANTIC_SCHOLAR_PAPER_URL.format(paper_id=quote(source_key.source_id, safe="")),
                params={"fields": SEMANTIC_SCHOLAR_FIELDS},
            )
            response.raise_for_status()
        return parse_semantic_scholar_paper(response.json(), source_key)


def parse_semantic_scholar_paper(payload: dict, source_key: SourceKey) -> PaperMetadata:
    title = payload.get("title") or source_key.source_id
    authors = [
        str(author.get("name"))
        for author in payload.get("authors") or []
        if isinstance(author, dict) and author.get("name")
    ]
    categories = _categories(payload)
    return PaperMetadata(
        source_type=source_key.source_type,
        source_id=source_key.source_id,
        title=_clean_text(str(title)),
        authors=authors,
        abstract=_clean_text(payload.get("abstract") or ""),
        categories=categories,
        primary_category=categories[0] if categories else None,
        published_at=_publication_date(payload),
        updated_at=None,
        canonical_url=payload.get("url") or source_key.canonical_url,
        pdf_url=source_key.pdf_url,
    )


def _strip_slack_wrapping(url: str) -> str:
    text = url.strip("<>")
    if "|" in text:
        text = text.split("|", 1)[0]
    return text


def _categories(payload: dict) -> list[str]:
    values = []
    for key in ["fieldsOfStudy", "publicationTypes"]:
        for value in payload.get(key) or []:
            if value:
                values.append(str(value))
    venue = payload.get("venue")
    if venue:
        values.append(str(venue))
    return _dedupe(values)


def _publication_date(payload: dict) -> datetime | None:
    value = payload.get("publicationDate")
    if value:
        parts = [int(part) for part in str(value).split("-")]
        if len(parts) == 3:
            return datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
        if len(parts) == 2:
            return datetime(parts[0], parts[1], 1, tzinfo=timezone.utc)
        if len(parts) == 1:
            return datetime(parts[0], 1, 1, tzinfo=timezone.utc)
    year = payload.get("year")
    if year:
        return datetime(int(year), 1, 1, tzinfo=timezone.utc)
    return None


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        clean = _clean_text(value)
        key = clean.lower()
        if clean and key not in seen:
            deduped.append(clean)
            seen.add(key)
    return deduped
