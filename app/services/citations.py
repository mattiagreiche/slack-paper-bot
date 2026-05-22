import re

import httpx
from sqlalchemy.orm import Session

from app.bibtex import paper_to_bibtex
from app.models import Paper, PaperCitation, utcnow

ARXIV_BIBTEX_URL = "https://arxiv.org/bibtex/{source_id}"
ARXIV_ABS_URL = "https://arxiv.org/abs/{source_id}"
CROSSREF_DOI_URL = "https://dx.doi.org/{doi}"


async def refresh_citation(db: Session, paper: Paper) -> PaperCitation | None:
    if paper.source_type != "arxiv":
        return None

    bibtex, provider, source_url = await fetch_arxiv_button_bibtex(paper.source_id)
    citation = db.get(PaperCitation, paper.id)
    if citation is None:
        citation = PaperCitation(
            paper_id=paper.id,
            bibtex=bibtex,
            provider=provider,
            source_url=source_url,
        )
        db.add(citation)
    else:
        citation.bibtex = bibtex
        citation.provider = provider
        citation.source_url = source_url
        citation.fetched_at = utcnow()
    db.flush()
    return citation


async def fetch_arxiv_button_bibtex(source_id: str) -> tuple[str, str, str]:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        doi = await _fetch_arxiv_page_citation_doi(client, source_id)
        if doi:
            response = await client.get(
                CROSSREF_DOI_URL.format(doi=doi),
                headers={"Accept": "application/x-bibtex"},
            )
            response.raise_for_status()
            return _format_crossref_bibtex(response.text), "Crossref Citation Formatting Service", str(response.url)

        source_url = ARXIV_BIBTEX_URL.format(source_id=source_id)
        response = await client.get(source_url)
        response.raise_for_status()
        return response.text.strip() + "\n", "arXiv API", source_url


def preferred_bibtex(paper: Paper) -> str:
    if paper.citation and paper.citation.bibtex:
        return paper.citation.bibtex
    return paper_to_bibtex(paper)


async def _fetch_arxiv_page_citation_doi(client: httpx.AsyncClient, source_id: str) -> str | None:
    response = await client.get(ARXIV_ABS_URL.format(source_id=source_id))
    response.raise_for_status()
    match = re.search(r'<meta\s+name="citation_doi"\s+content="([^"]+)"', response.text)
    if not match:
        return None
    return match.group(1).strip()


def _format_crossref_bibtex(data: str) -> str:
    value = data.strip()
    value = re.sub(r"},", "},\n  ", value)
    value = value.replace(", title=", ",\n   title=")
    value = value.replace("}}", "}\n}")
    return value + "\n"
