import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", name="uq_papers_source"),
        Index("ix_papers_source", "source_type", "source_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    normalized_title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[str | None] = mapped_column(Text)
    primary_category: Mapped[str | None] = mapped_column(String(80))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    metadata_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    metadata_error: Mapped[str | None] = mapped_column(Text)
    metadata_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_metadata_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    mentions: Mapped[list["SlackMention"]] = relationship(back_populates="paper")
    citation: Mapped["PaperCitation | None"] = relationship(back_populates="paper", uselist=False)
    related_run: Mapped["RelatedPaperRun | None"] = relationship(
        back_populates="paper",
        uselist=False,
    )


class PaperCitation(Base):
    __tablename__ = "paper_citations"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    bibtex: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    paper: Mapped[Paper] = relationship(back_populates="citation")


class SlackChannel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_backfilled_ts: Mapped[str | None] = mapped_column(String(32))
    last_catchup_ts: Mapped[str | None] = mapped_column(String(32))


class SlackUser(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    team_id: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(160))
    real_name: Mapped[str | None] = mapped_column(String(160))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SlackMention(Base):
    __tablename__ = "slack_mentions"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "message_ts",
            "paper_id",
            name="uq_slack_mention",
        ),
        Index("ix_slack_mentions_channel_ts", "channel_id", "message_ts"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id"), nullable=False)
    team_id: Mapped[str | None] = mapped_column(String(80))
    channel_id: Mapped[str] = mapped_column(String(80), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(120), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(80))
    user_name: Mapped[str | None] = mapped_column(String(160))
    message_ts: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_ts: Mapped[str | None] = mapped_column(String(32))
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    slack_permalink: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    paper: Mapped[Paper] = relationship(back_populates="mentions")


class ZoteroCollectionSync(Base):
    __tablename__ = "zotero_collection_syncs"

    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id"), primary_key=True)
    zotero_collection_key: Mapped[str | None] = mapped_column(String(32))
    sync_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    sync_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ZoteroItemSync(Base):
    __tablename__ = "zotero_item_syncs"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    zotero_item_key: Mapped[str | None] = mapped_column(String(32))
    zotero_note_key: Mapped[str | None] = mapped_column(String(32))
    sync_status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    sync_error: Mapped[str | None] = mapped_column(Text)
    sync_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_sync_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SlackInstallation(Base):
    __tablename__ = "slack_installations"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_slack_installation_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    app_id: Mapped[str | None] = mapped_column(String(80))
    team_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    team_name: Mapped[str] = mapped_column(String(160), nullable=False)
    bot_user_id: Mapped[str] = mapped_column(String(80), nullable=False)
    encrypted_bot_token: Mapped[str] = mapped_column(Text, nullable=False)
    granted_scopes: Mapped[str] = mapped_column(Text, nullable=False)
    credential_status: Mapped[str] = mapped_column(
        String(24),
        default="pending",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status_code: Mapped[str] = mapped_column(
        String(48),
        default="awaiting_activation",
        nullable=False,
    )
    status_message: Mapped[str] = mapped_column(
        String(240),
        default="Slack authorization is awaiting operator activation",
        nullable=False,
    )
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_oauth_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class TrialZoteroDestination(Base):
    __tablename__ = "trial_zotero_destinations"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_trial_zotero_destination_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    group_id: Mapped[str] = mapped_column(String(80), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(160))
    api_base_url: Mapped[str] = mapped_column(
        String(255),
        default="https://api.zotero.org",
        nullable=False,
    )
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    status_code: Mapped[str] = mapped_column(
        String(48),
        default="awaiting_verification",
        nullable=False,
    )
    status_message: Mapped[str] = mapped_column(
        String(240),
        default="Zotero destination is awaiting verification",
        nullable=False,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class SlackOAuthAttempt(Base):
    __tablename__ = "slack_oauth_attempts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(16), default="install", nullable=False)
    expected_team_id: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    result_code: Mapped[str | None] = mapped_column(String(48))
    result_message: Mapped[str | None] = mapped_column(String(240))
    result_team_id: Mapped[str | None] = mapped_column(String(80))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RelatedPaperRun(Base):
    __tablename__ = "related_paper_runs"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), default="semantic_scholar", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    query_id: Mapped[str | None] = mapped_column(String(220))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_since_zotero_sync: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    paper: Mapped[Paper] = relationship(back_populates="related_run")
    suggestions: Mapped[list["RelatedPaperSuggestion"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class RelatedPaperSuggestion(Base):
    __tablename__ = "related_paper_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "paper_id",
            "provider",
            "suggested_paper_id",
            name="uq_related_suggestion",
        ),
        Index("ix_related_suggestions_paper_rank", "paper_id", "rank"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    paper_id: Mapped[str] = mapped_column(ForeignKey("related_paper_runs.paper_id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), default="semantic_scholar", nullable=False)
    suggested_paper_id: Mapped[str] = mapped_column(String(160), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    publication_date: Mapped[str | None] = mapped_column(String(32))
    venue: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    external_ids: Mapped[str | None] = mapped_column(Text)
    citation_count: Mapped[int | None] = mapped_column(Integer)
    fields_of_study: Mapped[str | None] = mapped_column(Text)
    publication_types: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    run: Mapped[RelatedPaperRun] = relationship(back_populates="suggestions")


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="processed", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
