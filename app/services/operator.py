from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Paper, ZoteroItemSync, utcnow


def retry_metadata(db: Session, paper_id: str) -> Paper | None:
    paper = db.get(Paper, paper_id)
    if paper is None:
        return None
    paper.metadata_status = "pending"
    paper.metadata_error = None
    paper.next_metadata_retry_at = None
    db.commit()
    return paper


def retry_zotero_sync(db: Session, paper_id: str) -> Paper | None:
    paper = db.get(Paper, paper_id)
    if paper is None:
        return None

    sync = db.get(ZoteroItemSync, paper.id)
    if sync is None:
        sync = ZoteroItemSync(paper_id=paper.id)
        db.add(sync)
        db.flush()

    sync.sync_status = "pending"
    sync.sync_error = None
    sync.next_sync_retry_at = utcnow()
    db.commit()
    return paper


def redact_error(value: str | None) -> str:
    if not value:
        return ""

    text = value
    settings = get_settings()
    for secret in [
        settings.app_secret_key,
        settings.shared_password,
        settings.slack_signing_secret,
        settings.slack_bot_token,
        settings.zotero_api_key,
    ]:
        if secret:
            text = text.replace(secret, "[redacted]")

    text = re.sub(r"xox[baprs]-[A-Za-z0-9-]+", "[redacted]", text)
    text = re.sub(r"(?i)(api[_ -]?key|token|secret)=\S+", r"\1=[redacted]", text)
    return text[:240]
