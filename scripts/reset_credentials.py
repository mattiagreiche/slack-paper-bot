import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, init_db
from app.models import (
    SlackInstallation,
    SlackOAuthAttempt,
    TrialZoteroDestination,
    ZoteroCollectionSync,
    ZoteroItemSync,
)
from scripts.reset_archive import reset_archive

FULL_RESET_CONFIRMATION = "FULL-CREDENTIAL-RESET"


def reset_credentials(db, confirmation, include_archive=False) -> None:
    """Remove persisted credentials after exact operator confirmation."""
    if confirmation != FULL_RESET_CONFIRMATION:
        raise ValueError(
            f"Credential reset requires literal confirmation {FULL_RESET_CONFIRMATION!r}."
        )

    if include_archive:
        reset_archive(db, commit=False)
    else:
        db.query(ZoteroItemSync).delete(synchronize_session=False)
        db.query(ZoteroCollectionSync).delete(synchronize_session=False)

    db.query(SlackOAuthAttempt).delete(synchronize_session=False)
    db.query(SlackInstallation).delete(synchronize_session=False)
    db.query(TrialZoteroDestination).delete(synchronize_session=False)
    db.commit()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Remove Slack and Zotero credentials. Archive data is preserved unless "
            "--include-archive is supplied."
        )
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"must be exactly {FULL_RESET_CONFIRMATION}",
    )
    parser.add_argument(
        "--include-archive",
        action="store_true",
        help="also delete papers, Slack archive records, and derived data",
    )
    return parser


def main(argv=None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.confirm != FULL_RESET_CONFIRMATION:
        parser.error(f"--confirm must be exactly {FULL_RESET_CONFIRMATION}")

    init_db()
    with SessionLocal() as db:
        reset_credentials(
            db,
            confirmation=args.confirm,
            include_archive=args.include_archive,
        )

    archive_message = " Archive data was also cleared." if args.include_archive else ""
    print(f"Credentials cleared. Slack must be authorized again.{archive_message}")


if __name__ == "__main__":
    main()
