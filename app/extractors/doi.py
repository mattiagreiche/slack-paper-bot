import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import quote, unquote, urlparse

import httpx

from app.extractors.base import PaperMetadata, SourceKey

CROSSREF_WORKS_URL = "https://api.crossref.org/works/{doi}"


class DoiExtractor:
    source_type = "doi"

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
        if host not in {"doi.org", "dx.doi.org"}:
            raise ValueError("not a DOI resolver URL")

        doi = canonicalize_doi(unquote(parsed.path.lstrip("/")))
        return SourceKey(
            source_type=self.source_type,
            source_id=doi,
            canonical_url=f"https://doi.org/{doi}",
            pdf_url=None,
        )

    async def fetch_metadata(self, source_key: SourceKey) -> PaperMetadata:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                CROSSREF_WORKS_URL.format(doi=quote(source_key.source_id, safe="")),
            )
            response.raise_for_status()
        return parse_crossref_work(response.json(), source_key)


def canonicalize_doi(raw_doi: str) -> str:
    clean = raw_doi.strip()
    clean = re.sub(r"^(?:doi:)", "", clean, flags=re.IGNORECASE).strip()
    clean = clean.split("?", 1)[0].split("#", 1)[0]
    clean = clean.rstrip(".,;)")
    if not re.match(r"^10\.\d{4,9}/\S+$", clean, flags=re.IGNORECASE):
        raise ValueError(f"invalid DOI: {raw_doi}")
    return clean.lower()


def parse_crossref_work(payload: dict, source_key: SourceKey) -> PaperMetadata:
    message = payload.get("message") or {}
    title = _first(message.get("title")) or source_key.source_id
    abstract = _clean_html(message.get("abstract") or "")
    authors = [_format_author(author) for author in message.get("author") or []]
    authors = [author for author in authors if author]
    categories = _categories(message)
    published_at = _date_from_parts(
        message.get("published-print")
        or message.get("published-online")
        or message.get("published")
        or message.get("created")
        or message.get("issued")
    )

    return PaperMetadata(
        source_type=source_key.source_type,
        source_id=source_key.source_id,
        title=_clean_text(unescape(title)),
        authors=authors,
        abstract=_clean_text(abstract),
        categories=categories,
        primary_category=categories[0] if categories else None,
        published_at=published_at,
        updated_at=_date_from_parts(message.get("indexed")),
        canonical_url=source_key.canonical_url,
        pdf_url=source_key.pdf_url,
    )


def _strip_slack_wrapping(url: str) -> str:
    text = url.strip("<>")
    if "|" in text:
        text = text.split("|", 1)[0]
    return text


def _first(value: object) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None


def _format_author(author: dict) -> str:
    literal = author.get("name")
    if literal:
        return str(literal)
    given = author.get("given")
    family = author.get("family")
    return " ".join(str(part) for part in [given, family] if part).strip()


def _categories(message: dict) -> list[str]:
    values = []
    for value in message.get("subject") or []:
        if value:
            values.append(str(value))
    work_type = message.get("type")
    if work_type:
        values.append(str(work_type))
    container = _first(message.get("container-title"))
    if container:
        values.append(container)
    return _dedupe(values)


def _date_from_parts(value: object) -> datetime | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list) or not parts[0]:
        return None
    year = int(parts[0][0])
    month = int(parts[0][1]) if len(parts[0]) > 1 else 1
    day = int(parts[0][2]) if len(parts[0]) > 2 else 1
    return datetime(year, month, day, tzinfo=timezone.utc)


def _clean_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return unescape(without_tags)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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
