import time

from app.config import get_settings
from app.database import SessionLocal, init_db
from app.models import SlackChannel
from app.services.credentials import CredentialCipher, CredentialEncryptionError
from app.services.installations import (
    SlackWorkspaceContext,
    ZoteroDestinationContext,
    get_verified_zotero_context,
)
from app.services.legacy_slack import resolve_configured_workspace_context
from app.services.metadata import refresh_pending_metadata_sync
from app.services.related import refresh_pending_related_papers_sync
from app.services.slack import (
    SlackApiClient,
    SlackApiError,
    backfill_channel,
    deactivate_invalid_credential,
)
from app.services.zotero import ZoteroApiClient, ZoteroSettings, sync_ready_papers_to_zotero_sync


def main() -> None:
    settings = get_settings()
    init_db()
    while True:
        with SessionLocal() as db:
            workspace, destination = _runtime_contexts(db)
            refreshed = _refresh_metadata_for_runtime(db, workspace, destination)
            print(f"metadata refreshed={refreshed}", flush=True)
            if workspace is not None and destination is not None:
                zotero_client = ZoteroApiClient(
                    ZoteroSettings(
                        api_key=destination.api_key,
                        group_id=destination.group_id,
                        api_base_url=destination.api_base_url,
                    )
                )
                zotero_synced = sync_ready_papers_to_zotero_sync(
                    db,
                    client=zotero_client,
                    team_id=workspace.team_id,
                )
                print(f"zotero synced={zotero_synced}", flush=True)
                related_refreshed = refresh_pending_related_papers_sync(
                    db,
                    team_id=workspace.team_id,
                )
                print(f"related refreshed={related_refreshed}", flush=True)
                if related_refreshed:
                    zotero_notes_refreshed = sync_ready_papers_to_zotero_sync(
                        db,
                        client=zotero_client,
                        team_id=workspace.team_id,
                    )
                    print(f"zotero notes refreshed={zotero_notes_refreshed}", flush=True)

                client = SlackApiClient(workspace.bot_token)
                for channel in (
                    db.query(SlackChannel)
                    .filter(
                        SlackChannel.team_id == workspace.team_id,
                        SlackChannel.is_private.is_(False),
                    )
                    .all()
                ):
                    try:
                        count = _catch_up_channel(db, client, workspace, channel)
                        print(f"catchup channel={channel.name} mentions={count}", flush=True)
                    except SlackApiError as exc:
                        if deactivate_invalid_credential(
                            db,
                            team_id=workspace.team_id,
                            error=exc,
                        ):
                            print("catchup stopped: Slack credential is invalid", flush=True)
                            break
                        print(
                            f"catchup failed channel={channel.id} code={exc.error_code}",
                            flush=True,
                        )
                    except Exception:  # noqa: BLE001 - worker should keep running.
                        print(f"catchup failed channel={channel.id}", flush=True)
        time.sleep(settings.worker_interval_seconds)


def _catch_up_channel(
    db,
    client: SlackApiClient,
    workspace: SlackWorkspaceContext,
    channel: SlackChannel,
) -> int:
    import asyncio

    if channel.team_id != workspace.team_id or channel.is_private:
        return 0
    return asyncio.run(
        backfill_channel(
            db,
            client,
            workspace,
            channel.id,
            oldest=channel.last_catchup_ts,
            latest=None,
            limit=get_settings().backfill_limit_per_channel,
        )
    )


def _runtime_contexts(
    db,
) -> tuple[SlackWorkspaceContext | None, ZoteroDestinationContext | None]:
    settings = get_settings()
    cipher = _cipher(settings.credential_encryption_key)
    workspace = resolve_configured_workspace_context(
        db,
        settings=settings,
    )
    destination = get_verified_zotero_context(db, cipher=cipher) if cipher else None
    return workspace, destination


def _refresh_metadata_for_runtime(
    db,
    workspace: SlackWorkspaceContext | None,
    destination: ZoteroDestinationContext | None,
) -> int:
    if workspace is None or destination is None:
        return 0
    return refresh_pending_metadata_sync(db, team_id=workspace.team_id)


def _cipher(key: str | None) -> CredentialCipher | None:
    try:
        return CredentialCipher(key)
    except CredentialEncryptionError:
        return None


if __name__ == "__main__":
    main()
