import time

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models import SlackChannel
from app.services.metadata import refresh_pending_metadata_sync
from app.services.slack import SlackApiClient, backfill_channel


def main() -> None:
    settings = get_settings()
    init_db()
    while True:
        with SessionLocal() as db:
            refreshed = refresh_pending_metadata_sync(db)
            print(f"metadata refreshed={refreshed}", flush=True)
            if settings.slack_bot_token:
                client = SlackApiClient(settings.slack_bot_token)
                for channel in db.query(SlackChannel).all():
                    try:
                        count = _catch_up_channel(db, client, channel)
                        print(f"catchup channel={channel.name} mentions={count}", flush=True)
                    except Exception as exc:  # noqa: BLE001 - worker should keep running.
                        if "missing_scope" in str(exc):
                            print(
                                "catchup skipped: Slack token is missing channel read scopes "
                                "(add channels:read/groups:read and reinstall the app)",
                                flush=True,
                            )
                            continue
                        print(f"catchup failed channel={channel.id} error={exc}", flush=True)
        time.sleep(settings.worker_interval_seconds)


def _catch_up_channel(db, client: SlackApiClient, channel: SlackChannel) -> int:
    import asyncio

    return asyncio.run(
        backfill_channel(
            db,
            client,
            channel.id,
            oldest=channel.last_catchup_ts,
            latest=None,
            limit=get_settings().backfill_limit_per_channel,
        )
    )


if __name__ == "__main__":
    main()
