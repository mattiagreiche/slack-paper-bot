import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from app.models import IngestionEvent, Paper, PaperCitation, SlackChannel, SlackMention, SlackUser


def main() -> None:
    init_db()
    with SessionLocal() as db:
        for model in [PaperCitation, SlackMention, IngestionEvent, Paper, SlackChannel, SlackUser]:
            db.query(model).delete()
        db.commit()
    print("Cleared archive data.")


if __name__ == "__main__":
    main()
