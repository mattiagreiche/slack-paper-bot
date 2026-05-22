from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models import Paper, SlackMention


@dataclass(frozen=True)
class PaperSearchResult:
    paper: Paper
    mention_count: int
    latest_mention_at: datetime | None


def search_papers(
    db: Session,
    *,
    query: str | None = None,
    channel_id: str | None = None,
    user: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "recent",
    limit: int = 100,
) -> list[PaperSearchResult]:
    mention_filters = []
    if channel_id:
        mention_filters.append(SlackMention.channel_id == channel_id)
    if user:
        needle = f"%{user}%"
        mention_filters.append(
            or_(
                SlackMention.user_name.ilike(needle),
                SlackMention.user_id.ilike(needle),
            )
        )
    if date_from:
        mention_filters.append(
            SlackMention.posted_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to:
        mention_filters.append(
            SlackMention.posted_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        )

    mention_stmt = select(
        SlackMention.paper_id.label("paper_id"),
        func.count(SlackMention.id).label("mention_count"),
        func.max(SlackMention.posted_at).label("latest_mention_at"),
    )
    if mention_filters:
        mention_stmt = mention_stmt.where(and_(*mention_filters))
    mention_stats = mention_stmt.group_by(SlackMention.paper_id).subquery()

    stmt = (
        select(Paper, mention_stats.c.mention_count, mention_stats.c.latest_mention_at)
        .join(mention_stats, mention_stats.c.paper_id == Paper.id)
        .where(Paper.metadata_status != "ignored")
    )

    if query:
        if db.bind and db.bind.dialect.name == "postgresql":
            vector = func.to_tsvector(
                "english",
                func.concat_ws(
                    " ",
                    func.coalesce(Paper.title, ""),
                    func.coalesce(Paper.authors, ""),
                    func.coalesce(Paper.abstract, ""),
                    func.coalesce(Paper.categories, ""),
                ),
            )
            ts_query = func.plainto_tsquery("english", query)
            stmt = stmt.where(vector.op("@@")(ts_query))
        else:
            needle = f"%{query}%"
            stmt = stmt.where(
                or_(
                    Paper.title.ilike(needle),
                    Paper.authors.ilike(needle),
                    Paper.abstract.ilike(needle),
                    Paper.categories.ilike(needle),
                    Paper.source_id.ilike(needle),
                )
            )

    if sort == "mentions":
        stmt = stmt.order_by(desc(mention_stats.c.mention_count), desc(mention_stats.c.latest_mention_at))
    else:
        stmt = stmt.order_by(desc(mention_stats.c.latest_mention_at), desc(mention_stats.c.mention_count))

    rows = db.execute(stmt.limit(limit)).all()
    return [
        PaperSearchResult(
            paper=row[0],
            mention_count=int(row[1] or 0),
            latest_mention_at=row[2],
        )
        for row in rows
    ]
