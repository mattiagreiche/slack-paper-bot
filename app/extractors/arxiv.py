import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from urllib.parse import urlparse

import httpx

from app.extractors.base import PaperMetadata, SourceKey

ATOM = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_API_URL = "https://export.arxiv.org/api/query"


class ArxivExtractor:
    source_type = "arxiv"

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
        if host not in {"arxiv.org", "export.arxiv.org"}:
            raise ValueError("not an arXiv URL")

        path = parsed.path.strip("/")
        arxiv_id: str | None = None
        if path.startswith("abs/"):
            arxiv_id = path.removeprefix("abs/")
        elif path.startswith("pdf/"):
            arxiv_id = path.removeprefix("pdf/").removesuffix(".pdf")
        else:
            raise ValueError("unsupported arXiv path")

        canonical_id = canonicalize_arxiv_id(arxiv_id)
        return SourceKey(
            source_type=self.source_type,
            source_id=canonical_id,
            canonical_url=f"https://arxiv.org/abs/{canonical_id}",
            pdf_url=f"https://arxiv.org/pdf/{canonical_id}.pdf",
        )

    async def fetch_metadata(self, source_key: SourceKey) -> PaperMetadata:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(ARXIV_API_URL, params={"id_list": source_key.source_id})
            response.raise_for_status()
        return parse_arxiv_feed(response.text, source_key)


def canonicalize_arxiv_id(raw_id: str) -> str:
    clean = raw_id.strip().split("?")[0].split("#")[0].removesuffix(".pdf")
    clean = re.sub(r"v\d+$", "", clean, flags=re.IGNORECASE)

    new_style = re.fullmatch(r"(\d{4}\.\d{4,5})(?:v\d+)?", clean, flags=re.IGNORECASE)
    old_style = re.fullmatch(
        r"([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?",
        clean,
        flags=re.IGNORECASE,
    )
    if new_style:
        return new_style.group(1)
    if old_style:
        return old_style.group(1)
    raise ValueError(f"invalid arXiv id: {raw_id}")


def parse_arxiv_feed(xml_text: str, source_key: SourceKey) -> PaperMetadata:
    root = ET.fromstring(xml_text)
    entry = root.find("atom:entry", ATOM)
    if entry is None:
        raise ValueError(f"arXiv returned no entry for {source_key.source_id}")

    title = _clean_text(_required_text(entry, "atom:title"))
    abstract = _clean_text(_required_text(entry, "atom:summary"))
    authors = [
        _clean_text(name.text or "")
        for name in entry.findall("atom:author/atom:name", ATOM)
        if (name.text or "").strip()
    ]
    categories = [
        category.attrib["term"]
        for category in entry.findall("atom:category", ATOM)
        if category.attrib.get("term")
    ]
    primary_category = categories[0] if categories else None
    pdf_url = source_key.pdf_url
    for link in entry.findall("atom:link", ATOM):
        if link.attrib.get("title") == "pdf" and link.attrib.get("href"):
            pdf_url = link.attrib["href"]

    return PaperMetadata(
        source_type=source_key.source_type,
        source_id=source_key.source_id,
        title=unescape(title),
        authors=authors,
        abstract=unescape(abstract),
        categories=categories,
        primary_category=primary_category,
        published_at=_parse_dt(_optional_text(entry, "atom:published")),
        updated_at=_parse_dt(_optional_text(entry, "atom:updated")),
        canonical_url=source_key.canonical_url,
        pdf_url=pdf_url,
    )


def _strip_slack_wrapping(url: str) -> str:
    text = url.strip("<>")
    if "|" in text:
        text = text.split("|", 1)[0]
    return text


def _required_text(entry: ET.Element, path: str) -> str:
    text = _optional_text(entry, path)
    if text is None:
        raise ValueError(f"arXiv feed missing {path}")
    return text


def _optional_text(entry: ET.Element, path: str) -> str | None:
    node = entry.find(path, ATOM)
    if node is None:
        return None
    return node.text


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

