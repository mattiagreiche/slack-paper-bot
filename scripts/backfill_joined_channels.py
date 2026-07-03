import argparse
import asyncio
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.services.slack import SlackApiClient, backfill_channel, joined_channels


def date_to_slack_ts(value: str, *, end_of_day: bool = False) -> str:
    parsed = date.fromisoformat(value)
    clock = time.max if end_of_day else time.min
    return str(datetime.combine(parsed, clock, tzinfo=timezone.utc).timestamp())


async def run(limit: int, oldest: str | None, latest: str | None) -> None:
    settings = get_settings()
    if not settings.slack_bot_token:
        raise SystemExit("SLACK_BOT_TOKEN is required for backfill.")

    init_db()
    client = SlackApiClient(settings.slack_bot_token)
    channels = await joined_channels(client)
    if not channels:
        print("No joined channels found. Invite the bot to a channel first.")
        return

    with SessionLocal() as db:
        for channel in channels:
            count = await backfill_channel(
                db,
                client,
                channel["id"],
                oldest=oldest,
                latest=latest,
                limit=limit,
            )
            print(f"Backfilled {count} paper mentions from #{channel.get('name', channel['id'])}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill all public channels the bot has joined."
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--oldest", default=None, help="Slack timestamp lower bound.")
    parser.add_argument("--latest", default=None, help="Slack timestamp upper bound.")
    parser.add_argument("--since", default=None, help="UTC date lower bound, YYYY-MM-DD.")
    parser.add_argument("--until", default=None, help="UTC date upper bound, YYYY-MM-DD.")
    args = parser.parse_args()
    oldest = args.oldest or (date_to_slack_ts(args.since) if args.since else None)
    latest = args.latest or (date_to_slack_ts(args.until, end_of_day=True) if args.until else None)
    asyncio.run(run(args.limit, oldest, latest))


if __name__ == "__main__":
    main()
