from datetime import timezone

import pytest

from app.extractors.base import SourceKey
from app.extractors.semantic_scholar import (
    SemanticScholarExtractor,
    parse_semantic_scholar_paper,
)


def test_normalizes_semantic_scholar_paper_url():
    extractor = SemanticScholarExtractor()

    source = extractor.normalize(
        "https://www.semanticscholar.org/paper/Attention-Is-All-You-Need/Vaswani/204e3073870fae3d05bcbc2f6a8e263d9b72e776"
    )

    assert source.source_type == "semantic_scholar"
    assert source.source_id == "204e3073870fae3d05bcbc2f6a8e263d9b72e776"
    assert source.canonical_url.endswith("/204e3073870fae3d05bcbc2f6a8e263d9b72e776")


def test_rejects_non_paper_semantic_scholar_url():
    with pytest.raises(ValueError):
        SemanticScholarExtractor().normalize("https://www.semanticscholar.org/search?q=test")


def test_parse_semantic_scholar_paper_extracts_metadata():
    source_key = SourceKey(
        source_type="semantic_scholar",
        source_id="204e3073870fae3d05bcbc2f6a8e263d9b72e776",
        canonical_url="https://www.semanticscholar.org/paper/204e3073870fae3d05bcbc2f6a8e263d9b72e776",
    )
    metadata = parse_semantic_scholar_paper(
        {
            "paperId": "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
            "title": "Attention Is All You Need",
            "abstract": " A transformer paper. ",
            "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
            "fieldsOfStudy": ["Computer Science"],
            "publicationTypes": ["JournalArticle"],
            "venue": "NeurIPS",
            "publicationDate": "2017-06-12",
            "url": "https://www.semanticscholar.org/paper/204e3073870fae3d05bcbc2f6a8e263d9b72e776",
        },
        source_key,
    )

    assert metadata.title == "Attention Is All You Need"
    assert metadata.abstract == "A transformer paper."
    assert metadata.authors == ["Ashish Vaswani", "Noam Shazeer"]
    assert metadata.categories == ["Computer Science", "JournalArticle", "NeurIPS"]
    assert metadata.published_at.tzinfo == timezone.utc
