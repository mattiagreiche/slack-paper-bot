from datetime import timezone

import pytest

from app.extractors.base import SourceKey
from app.extractors.doi import DoiExtractor, canonicalize_doi, parse_crossref_work


def test_normalizes_doi_resolver_urls():
    extractor = DoiExtractor()

    source = extractor.normalize("https://doi.org/10.1145/3366423.3380138.")

    assert source.source_type == "doi"
    assert source.source_id == "10.1145/3366423.3380138"
    assert source.canonical_url == "https://doi.org/10.1145/3366423.3380138"
    assert extractor.normalize("https://dx.doi.org/10.1038/NPHYS1170").source_id == "10.1038/nphys1170"


def test_rejects_malformed_doi():
    with pytest.raises(ValueError):
        canonicalize_doi("not-a-doi")


def test_parse_crossref_work_extracts_metadata():
    source_key = SourceKey(
        source_type="doi",
        source_id="10.1145/3366423.3380138",
        canonical_url="https://doi.org/10.1145/3366423.3380138",
    )
    metadata = parse_crossref_work(
        {
            "message": {
                "title": ["A Paper Title"],
                "abstract": "<jats:p>A useful abstract.</jats:p>",
                "author": [
                    {"given": "Ada", "family": "Lovelace"},
                    {"name": "The Archive Team"},
                ],
                "subject": ["Computer Science", "Machine Learning"],
                "type": "proceedings-article",
                "container-title": ["Proceedings of Testing"],
                "published-online": {"date-parts": [[2020, 4, 23]]},
                "indexed": {"date-parts": [[2021, 1, 2]]},
            }
        },
        source_key,
    )

    assert metadata.title == "A Paper Title"
    assert metadata.abstract == "A useful abstract."
    assert metadata.authors == ["Ada Lovelace", "The Archive Team"]
    assert metadata.categories == [
        "Computer Science",
        "Machine Learning",
        "proceedings-article",
        "Proceedings of Testing",
    ]
    assert metadata.published_at.tzinfo == timezone.utc
    assert metadata.published_at.year == 2020
