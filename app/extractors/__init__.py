from app.extractors.arxiv import ArxivExtractor
from app.extractors.base import PaperExtractor, PaperMetadata, SourceKey

EXTRACTORS = [ArxivExtractor()]


def extractor_for_url(url: str) -> PaperExtractor | None:
    for extractor in EXTRACTORS:
        if extractor.can_handle(url):
            return extractor
    return None


def extractor_for_source(source_type: str) -> PaperExtractor | None:
    for extractor in EXTRACTORS:
        if extractor.source_type == source_type:
            return extractor
    return None


__all__ = [
    "EXTRACTORS",
    "ArxivExtractor",
    "PaperExtractor",
    "PaperMetadata",
    "SourceKey",
    "extractor_for_source",
    "extractor_for_url",
]

