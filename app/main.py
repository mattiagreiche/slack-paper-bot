from datetime import date, datetime, timezone
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, auth_token, is_authenticated
from app.config import get_settings
from app.database import get_db, init_db
from app.models import IngestionEvent, Paper, SlackChannel, SlackMention, SlackUser, ZoteroItemSync
from app.services.ingestion import ingest_slack_message
from app.services.citations import preferred_bibtex
from app.services.operator import redact_error, retry_metadata, retry_zotero_sync
from app.services.search import search_papers
from app.services.slack import (
    SlackApiClient,
    SlackSignatureError,
    enrich_slack_message,
    slack_message_from_event,
    verify_slack_signature,
)

app = FastAPI(title="Slack Paper Archive")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


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
            select(func.count(ZoteroItemSync.paper_id)).where(ZoteroItemSync.sync_status == "synced")
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
            select(func.count(ZoteroItemSync.paper_id)).where(ZoteroItemSync.sync_status == "failed")
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
    recent_events = db.scalars(
        select(IngestionEvent).order_by(IngestionEvent.created_at.desc()).limit(10)
    ).all()
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "counts": counts,
            "channels": channels,
            "metadata_work": metadata_work,
            "zotero_work": zotero_work,
            "recent_events": recent_events,
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

    message = slack_message_from_event(payload.get("event", {}), payload.get("team_id"))
    if message is not None:
        client = SlackApiClient(settings.slack_bot_token) if settings.slack_bot_token else None
        message = await enrich_slack_message(message, client)
        ingest_slack_message(db, message, event_key=payload.get("event_id"))
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
