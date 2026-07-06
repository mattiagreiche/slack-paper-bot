import re

from app.models import Paper


def paper_to_bibtex(paper: Paper) -> str:
    year = _year(paper)
    key = _bibtex_key(paper, year)
    if paper.source_type == "arxiv":
        fields = [
            ("title", paper.title or f"arXiv:{paper.source_id}"),
            ("author", _authors_for_bibtex(paper.authors)),
            ("year", year),
            ("eprint", paper.source_id),
            ("archivePrefix", "arXiv"),
            ("primaryClass", paper.primary_category),
            ("url", paper.canonical_url),
        ]
        body = _bibtex_body(fields)
        return f"@misc{{{key},\n{body}\n}}\n"

    entry_type = "article" if paper.source_type == "doi" else "misc"
    fields = [
        ("title", paper.title or f"{paper.source_type}:{paper.source_id}"),
        ("author", _authors_for_bibtex(paper.authors)),
        ("year", year),
        ("doi", paper.source_id if paper.source_type == "doi" else None),
        ("url", paper.canonical_url),
    ]
    body = _bibtex_body(fields)
    return f"@{entry_type}{{{key},\n{body}\n}}\n"


def _bibtex_body(fields: list[tuple[str, str | None]]) -> str:
    return ",\n".join(f"  {name} = {{{value}}}" for name, value in fields if value not in (None, ""))


def _authors_for_bibtex(authors: str | None) -> str | None:
    if not authors:
        return None
    return " and ".join(line.strip() for line in authors.splitlines() if line.strip())


def _year(paper: Paper) -> str:
    when = paper.published_at or paper.updated_at
    if when:
        return str(when.year)
    match = re.match(r"(\d{2})(\d{2})\.", paper.source_id) if paper.source_type == "arxiv" else None
    if match:
        return str(2000 + int(match.group(1)))
    return "n.d."


def _bibtex_key(paper: Paper, year: str) -> str:
    authors = [line.strip() for line in (paper.authors or "").splitlines() if line.strip()]
    first_author = authors[0].split()[-1] if authors else paper.source_type
    compact_title = re.sub(r"[^A-Za-z0-9]+", "", (paper.title or paper.source_id).title())[:32]
    return f"{re.sub(r'[^A-Za-z0-9]+', '', first_author)}{year}{compact_title}"
