from datetime import timezone

import pytest

from app.extractors.arxiv import ArxivExtractor, canonicalize_arxiv_id, parse_arxiv_feed
from app.extractors.base import SourceKey


def test_normalizes_abs_pdf_versions_and_old_ids():
    extractor = ArxivExtractor()

    assert extractor.normalize("https://arxiv.org/abs/2401.12345v2").source_id == "2401.12345"
    assert extractor.normalize("https://arxiv.org/pdf/2401.12345.pdf").source_id == "2401.12345"
    assert canonicalize_arxiv_id("hep-th/9901001v3") == "hep-th/9901001"


def test_rejects_malformed_arxiv_id():
    with pytest.raises(ValueError):
        canonicalize_arxiv_id("not-a-paper")


def test_parse_arxiv_feed_extracts_metadata():
    source_key = SourceKey(
        source_type="arxiv",
        source_id="1706.03762",
        canonical_url="https://arxiv.org/abs/1706.03762",
        pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
    )
    metadata = parse_arxiv_feed(
        """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title> Attention Is All You Need </title>
            <summary> A transformer paper. </summary>
            <published>2017-06-12T00:00:00Z</published>
            <updated>2017-06-12T00:00:00Z</updated>
            <author><name>Ashish Vaswani</name></author>
            <category term="cs.CL"/>
            <category term="cs.LG"/>
            <link title="pdf" href="https://arxiv.org/pdf/1706.03762"/>
          </entry>
        </feed>""",
        source_key,
    )

    assert metadata.title == "Attention Is All You Need"
    assert metadata.authors == ["Ashish Vaswani"]
    assert metadata.categories == ["cs.CL", "cs.LG"]
    assert metadata.published_at.tzinfo == timezone.utc

