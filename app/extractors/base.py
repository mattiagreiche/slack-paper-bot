from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class SourceKey:
    source_type: str
    source_id: str
    canonical_url: str
    pdf_url: str | None = None


@dataclass(frozen=True)
class PaperMetadata:
    source_type: str
    source_id: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    primary_category: str | None
    published_at: datetime | None
    updated_at: datetime | None
    canonical_url: str
    pdf_url: str | None


class PaperExtractor(Protocol):
    source_type: str

    def can_handle(self, url: str) -> bool:
        ...

    def normalize(self, url: str) -> SourceKey:
        ...

    async def fetch_metadata(self, source_key: SourceKey) -> PaperMetadata:
        ...

