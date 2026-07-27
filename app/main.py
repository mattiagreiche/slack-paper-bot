from datetime import date, datetime, timezone
import re
from urllib.parse import parse_qs

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, auth_token, is_authenticated
from app.config import get_settings
from app.database import get_db, init_db
from app.models import (
    IngestionEvent,
    Paper,
    RelatedPaperRun,
    SlackChannel,
    SlackInstallation,
    SlackMention,
    SlackOAuthAttempt,
    SlackUser,
    TrialZoteroDestination,
    ZoteroItemSync,
)
from app.services.credentials import CredentialCipher, CredentialEncryptionError
from app.services.ingestion import has_slack_identity_collision, ingest_slack_message
from app.services.citations import preferred_bibtex
from app.services.installations import (
    VALID_CREDENTIAL_STATUS,
    activate_installation,
    configure_trial_zotero_destination,
    deactivate_installation,
)
from app.services.legacy_slack import resolve_workspace_context
from app.services.operator import (
    redact_error,
    retry_metadata,
    retry_related_sync,
    retry_zotero_sync,
)
from app.services.related import related_suggestions_for_paper, semantic_scholar_source_url
from app.services.search import search_papers
from app.services.slack import (
    SlackApiClient,
    SlackApiError,
    SlackSignatureError,
    deactivate_invalid_credential,
    enrich_slack_message,
    slack_message_from_event,
    verify_slack_signature,
)
from app.services.slack_oauth import begin_slack_oauth, complete_slack_oauth
from app.services.zotero import verify_zotero_destination

app = FastAPI(title="Slack Paper Archive")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

SAFE_RUNTIME_REASON_CODES = frozenset(
    {
        "installation_inactive",
        "missing_team_id",
        "slack_api_unavailable",
        "slack_credential_invalid",
        "slack_credential_revoked",
        "slack_identity_collision",
        "unknown_workspace",
        "workspace_context_unavailable",
        "zotero_destination_unavailable",
    }
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login(request: Request) -> Response:
    form = parse_qs((await request.body()).decode())
    password = form.get("password", [""])[0]
    if password != get_settings().shared_password:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "That password did not match."},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE_NAME, auth_token(), httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str | None = None,
    channel: str | None = None,
    user: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "recent",
    db: Session = Depends(get_db),
):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    context = _search_context(
        db,
        request=request,
        q=q,
        channel=channel,
        user=user,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
    )
    return templates.TemplateResponse(
        request,
        "search.html",
        context,
    )


@app.get("/search/results")
def search_results(
    request: Request,
    q: str | None = None,
    channel: str | None = None,
    user: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "recent",
    db: Session = Depends(get_db),
):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")
    context = _search_context(
        db,
        request=request,
        q=q,
        channel=channel,
        user=user,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
    )
    html = templates.get_template("_results.html").render(context)
    return JSONResponse({"count": len(context["results"]), "html": html})


@app.get("/papers/{paper_id}.bib")
def paper_bibtex(
    paper_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return PlainTextResponse(preferred_bibtex(paper), media_type="text/plain")


@app.get("/papers/{paper_id}", response_class=HTMLResponse)
def paper_detail(
    paper_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    mentions = db.scalars(
        select(SlackMention)
        .where(SlackMention.paper_id == paper.id)
        .order_by(SlackMention.posted_at.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "detail.html",
        {
            "paper": paper,
            "mentions": mentions,
            "mention_count": len(mentions),
            "bibtex": preferred_bibtex(paper),
            "related_run": db.get(RelatedPaperRun, paper.id),
            "related_suggestions": related_suggestions_for_paper(db, paper.id),
            "semantic_scholar_source_url": semantic_scholar_source_url(paper),
        },
    )


@app.get("/status", response_class=HTMLResponse)
def status_page(request: Request, db: Session = Depends(get_db)):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    counts = {
        "papers": db.scalar(select(func.count(Paper.id))) or 0,
        "mentions": db.scalar(select(func.count(SlackMention.id))) or 0,
        "channels": db.scalar(select(func.count(SlackChannel.id))) or 0,
        "ready_metadata": db.scalar(
            select(func.count(Paper.id)).where(Paper.metadata_status == "ready")
        )
        or 0,
        "failed_metadata": db.scalar(
            select(func.count(Paper.id)).where(Paper.metadata_status == "failed")
        )
        or 0,
        "pending_metadata": db.scalar(
            select(func.count(Paper.id)).where(Paper.metadata_status == "pending")
        )
        or 0,
        "zotero_synced": db.scalar(
            select(func.count(ZoteroItemSync.paper_id)).where(
                ZoteroItemSync.sync_status == "synced"
            )
        )
        or 0,
        "zotero_pending": db.scalar(
            select(func.count(Paper.id))
            .outerjoin(ZoteroItemSync, ZoteroItemSync.paper_id == Paper.id)
            .where(
                Paper.metadata_status == "ready",
                or_(ZoteroItemSync.paper_id.is_(None), ZoteroItemSync.sync_status == "pending"),
            )
        )
        or 0,
        "zotero_failed": db.scalar(
            select(func.count(ZoteroItemSync.paper_id)).where(
                ZoteroItemSync.sync_status == "failed"
            )
        )
        or 0,
        "related_pending": db.scalar(
            select(func.count(RelatedPaperRun.paper_id)).where(RelatedPaperRun.status == "pending")
        )
        or 0,
        "related_ready": db.scalar(
            select(func.count(RelatedPaperRun.paper_id)).where(RelatedPaperRun.status == "ready")
        )
        or 0,
        "related_unavailable": db.scalar(
            select(func.count(RelatedPaperRun.paper_id)).where(
                RelatedPaperRun.status == "unavailable"
            )
        )
        or 0,
        "related_failed": db.scalar(
            select(func.count(RelatedPaperRun.paper_id)).where(RelatedPaperRun.status == "failed")
        )
        or 0,
    }
    channels = [
        {
            "channel": channel,
            "last_backfilled_at": _format_slack_ts(channel.last_backfilled_ts),
            "last_catchup_at": _format_slack_ts(channel.last_catchup_ts),
        }
        for channel in db.scalars(select(SlackChannel).order_by(SlackChannel.name)).all()
    ]
    metadata_work = [
        {
            "paper": paper,
            "status": paper.metadata_status,
            "error": redact_error(paper.metadata_error),
            "next_retry_at": paper.next_metadata_retry_at,
        }
        for paper in db.scalars(
            select(Paper)
            .where(Paper.metadata_status.in_(["pending", "failed"]))
            .order_by(Paper.created_at.desc())
            .limit(25)
        )
    ]
    zotero_work = [
        {
            "paper": paper,
            "sync": sync,
            "status": sync.sync_status if sync else "pending",
            "error": redact_error(sync.sync_error if sync else None),
            "next_retry_at": sync.next_sync_retry_at if sync else None,
        }
        for paper, sync in db.execute(
            select(Paper, ZoteroItemSync)
            .outerjoin(ZoteroItemSync, ZoteroItemSync.paper_id == Paper.id)
            .where(
                Paper.metadata_status == "ready",
                or_(
                    ZoteroItemSync.paper_id.is_(None),
                    ZoteroItemSync.sync_status.in_(["pending", "failed"]),
                ),
            )
            .order_by(Paper.last_seen_at.desc())
            .limit(25)
        ).all()
    ]
    related_work = [
        {
            "paper": paper,
            "run": run,
            "status": run.status,
            "error": redact_error(run.error),
            "next_retry_at": run.next_retry_at,
        }
        for paper, run in db.execute(
            select(Paper, RelatedPaperRun)
            .join(RelatedPaperRun, RelatedPaperRun.paper_id == Paper.id)
            .where(RelatedPaperRun.status.in_(["pending", "failed", "unavailable"]))
            .order_by(RelatedPaperRun.created_at.desc())
            .limit(25)
        ).all()
    ]
    recent_events = [
        _ingestion_event_view(event)
        for event in db.scalars(
            select(IngestionEvent).order_by(IngestionEvent.created_at.desc()).limit(10)
        ).all()
    ]
    installation = db.get(SlackInstallation, 1)
    destination = db.get(TrialZoteroDestination, 1)
    latest_oauth_attempt = db.scalar(
        select(SlackOAuthAttempt).order_by(SlackOAuthAttempt.created_at.desc()).limit(1)
    )
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "counts": counts,
            "channels": channels,
            "metadata_work": metadata_work,
            "zotero_work": zotero_work,
            "related_work": related_work,
            "recent_events": recent_events,
            "slack_installation": _installation_view(installation),
            "zotero_destination": _destination_view(destination),
            "latest_oauth_attempt": _oauth_attempt_view(latest_oauth_attempt),
        },
    )


@app.post("/operator/papers/{paper_id}/retry-metadata")
def retry_metadata_route(
    paper_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    if retry_metadata(db, paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return RedirectResponse("/status", status_code=303)


@app.post("/operator/papers/{paper_id}/retry-zotero")
def retry_zotero_route(
    paper_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    if retry_zotero_sync(db, paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return RedirectResponse("/status", status_code=303)


@app.post("/operator/papers/{paper_id}/retry-related")
def retry_related_route(
    paper_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    if retry_related_sync(db, paper_id) is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return RedirectResponse("/status", status_code=303)


@app.get("/slack/install")
def slack_install(request: Request, db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    if (
        not settings.slack_client_id
        or not settings.slack_client_secret
        or not settings.slack_oauth_redirect_uri
        or _credential_cipher(settings.credential_encryption_key) is None
    ):
        return _slack_install_result(
            request=request,
            success=False,
            message="Slack installation is not configured",
            status_code=503,
        )
    start = begin_slack_oauth(
        db,
        client_id=settings.slack_client_id,
        redirect_uri=settings.slack_oauth_redirect_uri,
    )
    return RedirectResponse(start.authorization_url, status_code=303)


@app.get("/slack/oauth/callback", response_class=HTMLResponse)
def slack_oauth_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    settings = get_settings()
    cipher = _credential_cipher(settings.credential_encryption_key)
    if (
        not settings.slack_client_id
        or not settings.slack_client_secret
        or not settings.slack_oauth_redirect_uri
        or cipher is None
    ):
        return _slack_install_result(
            request=request,
            success=False,
            message="Slack installation is not configured",
            status_code=503,
        )

    completion = complete_slack_oauth(
        db,
        state=state,
        code=code,
        error=error,
        redirect_uri=settings.slack_oauth_redirect_uri,
        exchange_code=lambda **values: _exchange_slack_oauth_code(
            client_id=settings.slack_client_id,
            client_secret=settings.slack_client_secret,
            code=values["code"],
            redirect_uri=values["redirect_uri"],
        ),
        cipher=cipher,
    )
    return _slack_install_result(
        request=request,
        success=completion.success,
        message=completion.message,
        status_code=200 if completion.success else 400,
    )


@app.post("/operator/slack/activate")
def activate_slack_installation(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    result = activate_installation(db)
    if not result.activated:
        return PlainTextResponse(result.reason, status_code=409)
    return RedirectResponse("/status", status_code=303)


@app.post("/operator/slack/deactivate")
def deactivate_slack_installation(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    result = deactivate_installation(db)
    if result.reason.startswith("No Slack"):
        return PlainTextResponse(result.reason, status_code=404)
    return RedirectResponse("/status", status_code=303)


@app.post("/operator/slack/replace/start")
def replace_slack_installation(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    settings = get_settings()
    if not settings.slack_client_id or not settings.slack_oauth_redirect_uri:
        return PlainTextResponse("Slack installation is not configured", status_code=503)
    start = begin_slack_oauth(
        db,
        client_id=settings.slack_client_id,
        redirect_uri=settings.slack_oauth_redirect_uri,
        replacement_approved=True,
    )
    return RedirectResponse(start.authorization_url, status_code=303)


@app.post("/operator/zotero-destination")
async def configure_zotero_destination(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    form = parse_qs((await request.body()).decode())
    group_id = form.get("group_id", [""])[0].strip()
    api_key = form.get("api_key", [""])[0]
    api_base_url = get_settings().zotero_api_base_url.strip().rstrip("/")
    if not group_id or not api_key or not api_base_url:
        return PlainTextResponse("Zotero destination is incomplete", status_code=400)

    cipher = _credential_cipher(get_settings().credential_encryption_key)
    if cipher is None:
        return PlainTextResponse(
            "Credential encryption is not configured correctly",
            status_code=503,
        )

    verification = await verify_zotero_destination(
        group_id=group_id,
        api_key=api_key,
        api_base_url=api_base_url,
    )

    result = configure_trial_zotero_destination(
        db,
        group_id=group_id,
        group_name=verification.group_name,
        api_key=api_key,
        api_base_url=api_base_url,
        cipher=cipher,
        verification_succeeded=verification.verified,
        verification_error=verification.error,
    )
    if not result.configured:
        return PlainTextResponse(result.reason, status_code=409)
    return RedirectResponse("/status", status_code=303)


@app.post("/slack/events")
async def slack_events(request: Request, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    body = await request.body()
    try:
        verify_slack_signature(
            body=body,
            timestamp=request.headers.get("X-Slack-Request-Timestamp"),
            signature=request.headers.get("X-Slack-Signature"),
            settings=settings,
        )
    except SlackSignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    payload = await request.json()
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    if payload.get("type") != "event_callback":
        return {"ok": True}

    team_id = payload.get("team_id")
    event_id = payload.get("event_id")
    if not isinstance(team_id, str) or not team_id:
        _record_slack_runtime_event(
            db,
            team_id="unknown",
            event_id=event_id,
            status="ignored",
            reason_code="missing_team_id",
        )
        return {"ok": True}

    event = payload.get("event", {})
    if isinstance(event, dict) and event.get("type") in {"app_uninstalled", "tokens_revoked"}:
        installation = db.get(SlackInstallation, 1)
        if installation is not None and installation.team_id == team_id:
            deactivate_invalid_credential(
                db,
                team_id=team_id,
                error=SlackApiError("events", "token_revoked"),
            )
            _record_slack_runtime_event(
                db,
                team_id=team_id,
                event_id=event_id,
                status="revoked",
                reason_code="slack_credential_revoked",
            )
        else:
            _record_slack_runtime_event(
                db,
                team_id=team_id,
                event_id=event_id,
                status="ignored",
                reason_code="unknown_workspace",
            )
        return {"ok": True}

    workspace = resolve_workspace_context(
        db,
        team_id=team_id,
        settings=settings,
        cipher=_credential_cipher(settings.credential_encryption_key),
    )
    if workspace is None:
        _record_slack_runtime_event(
            db,
            team_id=team_id,
            event_id=event_id,
            status="ignored",
            reason_code=_workspace_rejection_reason(db, team_id),
        )
        return {"ok": True}

    message = slack_message_from_event(event if isinstance(event, dict) else {}, team_id)
    if message is not None:
        client = SlackApiClient(workspace.bot_token)
        try:
            message = await enrich_slack_message(message, client)
        except SlackApiError as exc:
            deactivate_invalid_credential(db, team_id=team_id, error=exc)
            _record_slack_runtime_event(
                db,
                team_id=team_id,
                event_id=event_id,
                status="failed",
                reason_code=(
                    "slack_credential_invalid"
                    if exc.credential_invalid
                    else "slack_api_unavailable"
                ),
            )
            return {"ok": True}
        if has_slack_identity_collision(db, message):
            _record_slack_runtime_event(
                db,
                team_id=team_id,
                event_id=event_id,
                status="ignored",
                reason_code="slack_identity_collision",
            )
            return {"ok": True}
        ingest_slack_message(db, message, event_key=event_id)
    return {"ok": True}


def _search_context(
    db: Session,
    *,
    request: Request,
    q: str | None,
    channel: str | None,
    user: str | None,
    date_from: str | None,
    date_to: str | None,
    sort: str,
) -> dict:
    parsed_date_from = _parse_optional_date(date_from)
    parsed_date_to = _parse_optional_date(date_to)
    results = search_papers(
        db,
        query=_blank_to_none(q),
        channel_id=_blank_to_none(channel),
        user=_blank_to_none(user),
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        sort=sort,
    )
    return {
        "request": request,
        "results": results,
        "q": q or "",
        "selected_channel": channel or "",
        "user": user or "",
        "date_from": parsed_date_from.isoformat() if parsed_date_from else "",
        "date_to": parsed_date_to.isoformat() if parsed_date_to else "",
        "sort": sort if sort in {"recent", "mentions"} else "recent",
        "channels": db.scalars(select(SlackChannel).order_by(SlackChannel.name)).all(),
    }


def _parse_optional_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _blank_to_none(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


def _format_slack_ts(value: str | None) -> str | None:
    if not value:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return value
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _credential_cipher(key: str | None) -> CredentialCipher | None:
    try:
        return CredentialCipher(key)
    except CredentialEncryptionError:
        return None


def _exchange_slack_oauth_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    with httpx.Client(timeout=20) as client:
        response = client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Slack OAuth response was invalid")
    return payload


def _slack_install_result(
    *,
    request: Request,
    success: bool,
    message: str,
    status_code: int,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "slack_install_result.html",
        {"success": success, "message": message},
        status_code=status_code,
    )


def _installation_view(installation: SlackInstallation | None) -> dict | None:
    if installation is None:
        return None
    return {
        "team_id": installation.team_id,
        "team_name": installation.team_name,
        "bot_user_id": installation.bot_user_id,
        "granted_scopes": sorted(
            scope.strip() for scope in installation.granted_scopes.split(",") if scope.strip()
        ),
        "credential_status": installation.credential_status,
        "is_active": installation.is_active,
        "status_message": installation.status_message,
        "installed_at": installation.installed_at,
        "last_validated_at": installation.last_validated_at,
    }


def _destination_view(destination: TrialZoteroDestination | None) -> dict | None:
    if destination is None:
        return None
    return {
        "group_id": destination.group_id,
        "group_name": destination.group_name,
        "api_base_url": destination.api_base_url,
        "is_verified": destination.is_verified,
        "status_message": destination.status_message,
        "verified_at": destination.verified_at,
    }


def _oauth_attempt_view(attempt: SlackOAuthAttempt | None) -> dict | None:
    if attempt is None:
        return None
    return {
        "purpose": attempt.purpose,
        "status": attempt.status,
        "result_message": attempt.result_message,
        "result_team_id": attempt.result_team_id,
        "created_at": attempt.created_at,
        "completed_at": attempt.completed_at,
    }


def _record_slack_runtime_event(
    db: Session,
    *,
    team_id: str,
    event_id: object,
    status: str,
    reason_code: str,
) -> None:
    safe_team_id = _safe_runtime_identifier(team_id, fallback="unknown")
    safe_event_id = _safe_runtime_identifier(
        event_id,
        fallback=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"),
    )
    safe_reason_code = (
        reason_code if reason_code in SAFE_RUNTIME_REASON_CODES else "workspace_context_unavailable"
    )
    key = f"{safe_team_id}:runtime:{safe_event_id}"
    if db.get(IngestionEvent, key) is None:
        db.add(
            IngestionEvent(
                key=key,
                source="slack",
                status=status,
                error=safe_reason_code,
            )
        )
        db.commit()


def _workspace_rejection_reason(db: Session, team_id: str) -> str:
    installation = db.get(SlackInstallation, 1)
    if installation is None or installation.team_id != team_id:
        return "unknown_workspace"
    if installation.credential_status != VALID_CREDENTIAL_STATUS:
        return "slack_credential_invalid"
    if not installation.is_active:
        return "installation_inactive"
    destination = db.get(TrialZoteroDestination, 1)
    if (
        destination is None
        or not destination.is_verified
        or destination.status != "verified"
    ):
        return "zotero_destination_unavailable"
    return "workspace_context_unavailable"


def _ingestion_event_view(event: IngestionEvent) -> dict:
    team_id = event.key.split(":", 1)[0] if ":" in event.key else "unknown"
    reason_code = (
        event.error
        if event.error in SAFE_RUNTIME_REASON_CODES
        else None
    )
    return {
        "source": event.source,
        "status": event.status,
        "team_id": _safe_runtime_identifier(team_id, fallback="unknown"),
        "reason_code": reason_code,
        "created_at": event.created_at,
    }


def _safe_runtime_identifier(value: object, *, fallback: str) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        return value
    return fallback
