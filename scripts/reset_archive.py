import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from app.models import (
    IngestionEvent,
    Paper,
    PaperCitation,
    RelatedPaperRun,
    RelatedPaperSuggestion,
    SlackChannel,
    SlackMention,
    SlackUser,
    ZoteroCollectionSync,
    ZoteroItemSync,
)


def reset_archive(db, *, commit: bool = True) -> None:
    """Delete archive and derived sync data while preserving credentials."""
    models_in_delete_order = (
        RelatedPaperSuggestion,
        RelatedPaperRun,
        ZoteroItemSync,
        ZoteroCollectionSync,
        PaperCitation,
        SlackMention,
        IngestionEvent,
        Paper,
        SlackChannel,
        SlackUser,
    )
    for model in models_in_delete_order:
        db.query(model).delete(synchronize_session=False)
    if commit:
        db.commit()


def main() -> None:
    init_db()
    with SessionLocal() as db:
        reset_archive(db)
    print("Cleared archive data.")


if __name__ == "__main__":
    main()
