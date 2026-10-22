"""Doctor web console: minimal server-rendered pages (FastAPI + Jinja2, no JS framework) under /console.

Access requires CONSOLE_TOKEN (.env). The token is accepted as a cookie (set by the login form), the
`X-Console-Token` header, or `Authorization: Bearer <token>` for curl. With CONSOLE_TOKEN empty the console is
disabled (503) rather than open. Forms are plain POSTs; the session cookie is HttpOnly + SameSite=Lax.

The console never calls WhatsApp or the LLM itself: approve/edit/discard and mode changes go through
Orchestrator.handle_doctor_command, exactly as the WhatsApp commands do, so the same logging and policy apply."""
from __future__ import annotations

import hmac
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .db import AuditLog, Draft, Message, Patient, as_utc, get_setting, utcnow
from .orchestrator import MODE_KEY, Orchestrator
from .pricing import PRICES_USD_PER_MTOK, UsageRow, parse_usage_detail

COOKIE = "console_token"
EMERGENCY_EVENTS = ("emergency", "emergency_model")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["money"] = lambda v: f"${v:,.4f}" if v < 1 else f"${v:,.2f}"
templates.env.filters["num"] = lambda v: f"{int(v):,}"


def _ts(dt: Optional[datetime]) -> str:
    dt = as_utc(dt)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else ""


templates.env.filters["ts"] = _ts


class ConsoleAuthRequired(Exception):
    """Raised when no token was presented; the app-level handler redirects to the login page."""


def _presented_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Console-Token") or request.cookies.get(COOKIE)


def make_router(settings: Settings, SessionLocal: sessionmaker[Session], orchestrator_factory: Callable[[Session], Orchestrator]) -> APIRouter:
    router = APIRouter(prefix="/console", tags=["console"])

    def require_token(request: Request) -> None:
        if not settings.console_token:
            raise HTTPException(503, "Console disabled: set CONSOLE_TOKEN in .env")
        token = _presented_token(request)
        if not token:
            raise ConsoleAuthRequired()
        if not hmac.compare_digest(token.encode(), settings.console_token.encode()):
            raise HTTPException(403, "bad console token")

    def ctx(request: Request, db: Session, **extra) -> dict:
        return {"request": request, "settings": settings, "mode": get_setting(db, MODE_KEY, settings.default_mode),
                "pending_count": db.scalar(select(func.count()).select_from(Draft).where(Draft.status == "pending")) or 0,
                **extra}

    # ---------- login ----------
    @router.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, error: str = ""):
        if not settings.console_token:
            raise HTTPException(503, "Console disabled: set CONSOLE_TOKEN in .env")
        return templates.TemplateResponse(request, "login.html", {"request": request, "settings": settings, "error": error, "mode": "", "pending_count": 0})

    @router.post("/login")
    def login(request: Request, token: str = Form(...)):
        if not settings.console_token or not hmac.compare_digest(token.encode(), settings.console_token.encode()):
            return RedirectResponse("/console/login?error=1", status_code=303)
        resp = RedirectResponse("/console", status_code=303)
        resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=12 * 3600)
        return resp

    @router.post("/logout")
    def logout():
        resp = RedirectResponse("/console/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    # ---------- dashboard: drafts, mode, today's emergencies ----------
    @router.get("", response_class=HTMLResponse, dependencies=[Depends(require_token)])
    @router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_token)], include_in_schema=False)
    def dashboard(request: Request, notice: str = ""):
        with SessionLocal() as db:
            drafts = db.scalars(select(Draft).where(Draft.status == "pending").order_by(Draft.id.desc())).all()
            names = {p.wa_id: p.name for p in db.scalars(select(Patient).where(Patient.wa_id.in_({d.patient_wa_id for d in drafts}))).all()} if drafts else {}
            today = utcnow().date()
            recent = db.scalars(select(AuditLog).where(AuditLog.event.in_(EMERGENCY_EVENTS)).order_by(AuditLog.id.desc()).limit(200)).all()
            emergencies = [e for e in recent if as_utc(e.created_at).date() == today]
            patients = db.scalars(select(Patient).order_by(Patient.created_at.desc()).limit(50)).all()
            return templates.TemplateResponse(request, "dashboard.html", ctx(
                request, db, drafts=drafts, names=names, emergencies=emergencies, patients=patients, notice=notice, today=today))

    @router.post("/mode", dependencies=[Depends(require_token)])
    def set_mode(mode: str = Form(...)):
        if mode not in ("auto", "draft", "off"):
            raise HTTPException(400, "mode must be auto|draft|off")
        with SessionLocal() as db:
            orchestrator_factory(db).handle_doctor_command(mode)
        return RedirectResponse(f"/console?notice=Mode+set+to+{mode}", status_code=303)

    @router.post("/drafts/{draft_id}", dependencies=[Depends(require_token)])
    def decide(draft_id: int, action: str = Form(...), text: str = Form("")):
        letter = {"approve": "A", "edit": "E", "discard": "X"}.get(action)
        if not letter:
            raise HTTPException(400, "action must be approve|edit|discard")
        if action == "edit" and not text.strip():
            return RedirectResponse(f"/console?notice=Draft+{draft_id}%3A+type+your+reply+before+sending", status_code=303)
        with SessionLocal() as db:
            r = orchestrator_factory(db).handle_doctor_command(f"{letter}{draft_id} {text.strip()}".strip())
        return RedirectResponse(f"/console?notice=Draft+{draft_id}%3A+{r.get('outcome', '')}", status_code=303)

    # ---------- per-patient conversation ----------
    @router.get("/patients/{wa_id}", response_class=HTMLResponse, dependencies=[Depends(require_token)])
    def patient_view(request: Request, wa_id: str):
        with SessionLocal() as db:
            patient = db.get(Patient, wa_id)
            if not patient:
                raise HTTPException(404, "no such patient")
            messages = db.scalars(select(Message).where(Message.patient_wa_id == wa_id).order_by(Message.created_at, Message.id)).all()
            drafts = db.scalars(select(Draft).where(Draft.patient_wa_id == wa_id).order_by(Draft.id.desc())).all()
            return templates.TemplateResponse(request, "patient.html", ctx(request, db, patient=patient, messages=messages, drafts=drafts))

    # ---------- usage / cost ----------
    @router.get("/usage", response_class=HTMLResponse, dependencies=[Depends(require_token)])
    def usage(request: Request, days: int = 30):
        with SessionLocal() as db:
            rows = db.scalars(select(AuditLog).where(AuditLog.event == "llm_usage").order_by(AuditLog.id.desc()).limit(20000)).all()
            cutoff = utcnow().date().toordinal() - max(days, 1) + 1
            by_day: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tokens": 0, "usd": 0.0, "messages": 0, "assumed": False})
            by_patient: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tokens": 0, "usd": 0.0, "messages": 0, "assumed": False})
            by_model: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tokens": 0, "usd": 0.0, "messages": 0, "assumed": False})
            total = {"calls": 0, "tokens": 0, "usd": 0.0, "messages": 0, "assumed": False}
            for row in rows:
                day = as_utc(row.created_at).date()
                if day.toordinal() < cutoff:
                    continue
                u: UsageRow | None = parse_usage_detail(row.detail, settings.agent_model)
                if not u:
                    continue
                for bucket in (by_day[day.isoformat()], by_patient[row.patient_wa_id or "?"], by_model[u.model], total):
                    bucket["calls"] += u.calls
                    bucket["tokens"] += u.total_tokens
                    bucket["usd"] += u.usd
                    bucket["messages"] += 1
                    bucket["assumed"] = bucket["assumed"] or u.assumed_model
            return templates.TemplateResponse(request, "usage.html", ctx(
                request, db, days=days, total=total,
                by_day=sorted(by_day.items(), reverse=True),
                by_patient=sorted(by_patient.items(), key=lambda kv: -kv[1]["usd"]),
                by_model=sorted(by_model.items(), key=lambda kv: -kv[1]["usd"]),
                prices=PRICES_USD_PER_MTOK))

    return router


def install_auth_redirect(app) -> None:
    """Send browsers without a token to the login page instead of a bare 401."""
    @app.exception_handler(ConsoleAuthRequired)
    async def _redirect(request: Request, exc: ConsoleAuthRequired):
        return RedirectResponse("/console/login", status_code=303)
