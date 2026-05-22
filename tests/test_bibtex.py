from datetime import datetime, timezone

from app.bibtex import paper_to_bibtex
from app.models import Paper


def test_bibtex_uses_arxiv_fields():
    paper = Paper(
        source_type="arxiv",
        source_id="1706.03762",
        title="Attention Is All You Need",
        authors="Ashish Vaswani\nNoam Shazeer",
        primary_category="cs.CL",
        published_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
        canonical_url="https://arxiv.org/abs/1706.03762",
    )

    bibtex = paper_to_bibtex(paper)

    assert "@misc{" in bibtex
    assert "author = {Ashish Vaswani and Noam Shazeer}" in bibtex
    assert "eprint = {1706.03762}" in bibtex
    assert "archivePrefix = {arXiv}" in bibtex

