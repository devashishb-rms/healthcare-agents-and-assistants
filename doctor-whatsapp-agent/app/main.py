"""FastAPI app: Meta webhook (verify + receive), draft admin endpoints, and a local /simulate endpoint."""
from __future__ import annotations

import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from .agent import ClaudeAgent
from .config import get_settings
from .db import Draft, make_session_factory
from .media import transcribe
from .orchestrator import Inbound, Orchestrator
from .tools import Calendar, ClinicKB, Reports, ToolBox
from .whatsapp import WhatsAppClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sevadesk")

settings = get_settings()
SessionLocal = make_session_factory(settings.database_url)
wa = WhatsAppClient(settings.whatsapp_token, settings.whatsapp_phone_number_id, settings.whatsapp_api_version, dry_run=settings.dry_run)
toolbox = ToolBox(ClinicKB(settings.kb_path), Calendar(settings.calendar_path), Reports(settings.reports_path))
llm = ClaudeAgent(toolbox, settings.agent_model, settings.agent_effort, settings.enable_fallbacks, api_key=settings.anthropic_api_key or None, workspace_id=settings.anthropic_workspace_id or None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("SevaDesk up. dry_run=%s model=%s mode=%s", settings.dry_run, settings.agent_model, settings.default_mode)
    yield


app = FastAPI(title="SevaDesk – doctor's WhatsApp agent", lifespan=lifespan)


def process(m: Inbound) -> dict:
    with SessionLocal() as db:
        return Orchestrator(settings, db, wa, llm, toolbox).handle(m)


# ---------- Meta webhook ----------
@app.get("/webhook")
def verify(hub_mode: str = Query("", alias="hub.mode"), hub_token: str = Query("", alias="hub.verify_token"), hub_challenge: str = Query("", alias="hub.challenge")):
    if hub_mode == "subscribe" and hub_token == settings.whatsapp_verify_token:
        return int(hub_challenge) if hub_challenge.isdigit() else hub_challenge
    raise HTTPException(403, "verification failed")


def _verify_signature(raw: bytes, header: Optional[str]) -> None:
    if not settings.whatsapp_app_secret:
        return
    if not header or not header.startswith("sha256="):
        raise HTTPException(403, "missing signature")
    digest = hmac.new(settings.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, header[7:]):
        raise HTTPException(403, "bad signature")


def parse_webhook(payload: dict) -> list[Inbound]:
    """Flatten Meta's nested payload into Inbound objects (messages + Coexistence message_echoes)."""
    out: list[Inbound] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field, value = change.get("field"), change.get("value", {})
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            if field == "messages":
                for msg in value.get("messages", []):
                    t = msg.get("type")
                    ib = Inbound(wa_message_id=msg.get("id", ""), from_wa_id=msg.get("from", ""))
                    if t == "text":
                        ib.text = msg.get("text", {}).get("body", "")
                    elif t in ("audio", "image", "document", "video"):
                        ib.media_type = "audio" if t == "audio" else t
                        ib.media_id = msg.get(t, {}).get("id")
                        ib.text = msg.get(t, {}).get("caption", "") or ""
                    elif t == "interactive":
                        i = msg.get("interactive", {})
                        ib.text = (i.get("button_reply") or i.get("list_reply") or {}).get("title", "")
                    elif t == "button":
                        ib.text = msg.get("button", {}).get("text", "")
                    else:
                        ib.text = f"[{t} message]"
                    ib.attachments = []
                    ib_name = contacts.get(ib.from_wa_id)
                    if ib_name:
                        ib.attachments.append(f"WhatsApp profile name: {ib_name}")
                    out.append(ib)
            elif field == "message_echoes":
                for msg in value.get("message_echoes", []):
                    out.append(Inbound(wa_message_id=msg.get("id", ""), from_wa_id=msg.get("from", ""), to_wa_id=msg.get("to"),
                                       text=msg.get("text", {}).get("body", ""), is_echo=True))
    return out


def enrich_media(m: Inbound) -> None:
    if m.media_type == "audio" and m.media_id and settings.sarvam_api_key and not settings.dry_run:
        audio, mime = wa.download_media(m.media_id)
        tx = transcribe(audio, mime, settings.sarvam_api_key)
        m.attachments.append(f"voice note transcript: {tx}" if tx else "voice note received but could not be transcribed")


@app.post("/webhook")
async def receive(request: Request, background: BackgroundTasks):
    raw = await request.body()
    _verify_signature(raw, request.headers.get("X-Hub-Signature-256"))
    payload = await request.json()
    for m in parse_webhook(payload):
        wa.mark_read(m.wa_message_id) if not m.is_echo else None
        enrich_media(m)
        background.add_task(process, m)     # return 200 fast; Meta retries otherwise
    return {"status": "ok"}


# ---------- Admin / console ----------
@app.get("/health")
def health():
    return {"ok": True, "dry_run": settings.dry_run, "model": settings.agent_model}


@app.get("/drafts")
def list_drafts(status: str = "pending"):
    with SessionLocal() as db:
        rows = db.scalars(select(Draft).where(Draft.status == status).order_by(Draft.id.desc())).all()
        return [{"id": d.id, "patient": d.patient_wa_id, "patient_text": d.patient_text, "proposed_reply": d.proposed_reply,
                 "note": d.note_for_doctor, "status": d.status, "created_at": d.created_at.isoformat()} for d in rows]


class Decision(BaseModel):
    action: str            # approve | edit | discard
    text: Optional[str] = None


@app.post("/drafts/{draft_id}")
def decide(draft_id: int, body: Decision):
    letter = {"approve": "A", "edit": "E", "discard": "X"}.get(body.action)
    if not letter:
        raise HTTPException(400, "action must be approve|edit|discard")
    cmd = f"{letter}{draft_id} {body.text or ''}".strip()
    with SessionLocal() as db:
        return Orchestrator(settings, db, wa, llm, toolbox).handle_doctor_command(cmd)


@app.post("/mode/{mode}")
def set_mode(mode: str):
    if mode not in ("auto", "draft", "off"):
        raise HTTPException(400, "mode must be auto|draft|off")
    with SessionLocal() as db:
        return Orchestrator(settings, db, wa, llm, toolbox).handle_doctor_command(mode)


class Simulated(BaseModel):
    from_wa_id: str
    text: str
    message_id: Optional[str] = None


@app.post("/simulate")
def simulate(body: Simulated):
    """Local testing without WhatsApp: post a patient (or doctor-control) message and see what the agent does."""
    if not settings.dry_run:
        raise HTTPException(403, "simulate is only available in DRY_RUN mode")
    import uuid
    wa.sent.clear()
    result = process(Inbound(wa_message_id=body.message_id or f"sim-{uuid.uuid4()}", from_wa_id=body.from_wa_id, text=body.text))
    return {"result": result, "outbound": list(wa.sent)}
