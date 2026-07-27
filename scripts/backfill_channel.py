import argparse
import asyncio
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.services.legacy_slack import resolve_configured_workspace_context
from app.services.slack import (
    SlackApiClient,
    SlackApiError,
    backfill_channel,
    deactivate_invalid_credential,
)


def date_to_slack_ts(value: str, *, end_of_day: bool = False) -> str:
    parsed = date.fromisoformat(value)
    clock = time.max if end_of_day else time.min
    return str(datetime.combine(parsed, clock, tzinfo=timezone.utc).timestamp())


async def run(channel_id: str, oldest: str | None, latest: str | None, limit: int) -> None:
    init_db()
    with SessionLocal() as db:
        workspace = _active_workspace(db)
        try:
            count = await backfill_channel(
                db,
                SlackApiClient(workspace.bot_token),
                workspace,
                channel_id,
                oldest=oldest,
                latest=latest,
                limit=limit,
            )
        except SlackApiError as exc:
            deactivate_invalid_credential(
                db,
                team_id=workspace.team_id,
                error=exc,
            )
            raise SystemExit(f"Slack backfill failed: {exc.error_code}") from None
    print(f"Backfilled {count} paper mentions from {channel_id}.")


def _active_workspace(db):
    settings = get_settings()
    workspace = resolve_configured_workspace_context(
        db,
        settings=settings,
    )
    if workspace is None:
        raise SystemExit("An active Slack installation is required for backfill.")
    return workspace


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill one Slack channel by channel ID.")
    parser.add_argument("channel_id")
    parser.add_argument("--oldest", default=None, help="Slack timestamp lower bound.")
    parser.add_argument("--latest", default=None, help="Slack timestamp upper bound.")
    parser.add_argument("--since", default=None, help="UTC date lower bound, YYYY-MM-DD.")
    parser.add_argument("--until", default=None, help="UTC date upper bound, YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    oldest = args.oldest or (date_to_slack_ts(args.since) if args.since else None)
    latest = args.latest or (date_to_slack_ts(args.until, end_of_day=True) if args.until else None)
    asyncio.run(run(args.channel_id, oldest, latest, args.limit))


if __name__ == "__main__":
    main()
