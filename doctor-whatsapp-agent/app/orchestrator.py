"""Policy gate + routing. Order of checks is deliberate and must not be reordered:
dedupe -> doctor command -> consent/opt-out -> EMERGENCY gate -> echo/backoff -> mode -> LLM -> enforce action."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent import AgentContext, AgentResult, LLM
from .config import Settings
from .db import Draft, Message, Patient, as_utc, audit, get_setting, recent_history, set_setting, utcnow
from .safety import detect_emergency, emergency_script, guess_language, parse_doctor_command
from .tools import ToolBox, today_str
from .whatsapp import WhatsAppClient

log = logging.getLogger("sevadesk.orchestrator")

MODE_KEY = "mode"


@dataclass
class Inbound:
    wa_message_id: str
    from_wa_id: str
    text: str = ""
    media_type: Optional[str] = None      # audio | image | document | None
    media_id: Optional[str] = None
    is_echo: bool = False                 # message the doctor sent from the WhatsApp Business app (Coexistence)
    to_wa_id: Optional[str] = None        # for echoes: the patient
    attachments: list[str] = field(default_factory=list)   # transcripts / descriptions prepared by media.py


class Orchestrator:
    def __init__(self, settings: Settings, db: Session, wa: WhatsAppClient, llm: LLM, toolbox: ToolBox):
        self.s, self.db, self.wa, self.llm, self.toolbox = settings, db, wa, llm, toolbox

    # ---------- helpers ----------
    def mode(self) -> str:
        return get_setting(self.db, MODE_KEY, self.s.default_mode)

    def set_mode(self, mode: str) -> None:
        set_setting(self.db, MODE_KEY, mode)

    def _patient(self, wa_id: str) -> Patient:
        p = self.db.get(Patient, wa_id)
        if not p:
            p = Patient(wa_id=wa_id)
            self.db.add(p)
            self.db.commit()
        return p

    def _store(self, m: Inbound, direction: str, patient_wa_id: str, **kw) -> Message:
        row = Message(wa_message_id=m.wa_message_id or None, patient_wa_id=patient_wa_id, direction=direction,
                      body=m.text, media_type=m.media_type, media_id=m.media_id, **kw)
        self.db.add(row)
        self.db.commit()
        return row

    def _send(self, to: str, text: str, patient_wa_id: Optional[str] = None, action: str = "SEND") -> None:
        if not text:
            return
        self.wa.send_text(to, text)
        self.db.add(Message(patient_wa_id=patient_wa_id or to, direction="out", body=text, action=action))
        self.db.commit()

    def _page_doctor(self, text: str) -> None:
        if self.s.doctor_control_number:
            self.wa.send_text(self.s.doctor_control_number, text)

    def _eta(self) -> str:
        st = self.toolbox.calendar.status()
        return f"by {st['busy_until']}" if st.get("busy_until") else f"within about {self.s.holding_eta_minutes} minutes"

    def _prompt_vars(self) -> dict:
        st = self.toolbox.calendar.status()
        return {
            "assistant_name": self.s.assistant_name, "doctor_name": self.s.doctor_name,
            "doctor_qualifications": self.s.doctor_qualifications, "speciality": self.s.speciality,
            "nmc_reg_no": self.s.nmc_reg_no, "clinic_name": self.s.clinic_name, "city": self.s.city,
            "clinic_phone": self.s.clinic_phone, "regional_languages": self.s.regional_languages,
            "doctor_status": st["doctor_status"], "mode": self.mode(), "eta": self._eta(), "today": today_str(),
        }

    # ---------- entry point ----------
    def handle(self, m: Inbound) -> dict:
        """Process one inbound webhook message. Returns a small dict describing what happened (for logs/tests)."""
        # 1. dedupe (Meta retries webhooks for up to 7 days)
        if m.wa_message_id and self.db.scalar(select(Message).where(Message.wa_message_id == m.wa_message_id)):
            return {"outcome": "duplicate"}

        # 2. doctor's own app replies (Coexistence echo) -> record activity, stay silent
        if m.is_echo:
            if m.to_wa_id:
                p = self._patient(m.to_wa_id)
                p.doctor_last_reply_at = utcnow()
                self._store(m, "echo", m.to_wa_id)
            return {"outcome": "echo_recorded"}

        # 3. doctor control number -> commands
        if self.s.doctor_control_number and m.from_wa_id == self.s.doctor_control_number:
            self._store(m, "in", m.from_wa_id, classification="DOCTOR_CMD")
            return self.handle_doctor_command(m.text)

        patient = self._patient(m.from_wa_id)
        text = m.text or ""

        # 4. opt-out / consent
        if text.strip().upper() in {"STOP", "UNSUBSCRIBE"}:
            patient.opted_out = 1
            self.db.commit()
            self._store(m, "in", patient.wa_id, action="OPT_OUT")
            self._send(patient.wa_id, "Understood. The assistant will not message you again. For anything urgent, call the clinic directly.", patient.wa_id)
            audit(self.db, "opt_out", patient.wa_id)
            return {"outcome": "opted_out"}
        if patient.opted_out:
            self._store(m, "in", patient.wa_id, action="SILENT")
            self._page_doctor(f"Message from opted-out patient {patient.wa_id}: {text[:200]}")
            return {"outcome": "silent_opted_out"}
        first_contact = patient.consent_sent_at is None
        if first_contact:
            patient.consent_sent_at = utcnow()
            self.db.commit()
        elif patient.consent_at is None:
            patient.consent_at = utcnow()   # continuing after the notice = implied consent (TPG 2020 patient-initiated)
            self.db.commit()

        # 5. EMERGENCY gate (deterministic, before any LLM)
        hit = detect_emergency(text) or (detect_emergency(" ".join(m.attachments)) if m.attachments else None)
        if hit:
            self._store(m, "in", patient.wa_id, classification="EMERGENCY", action="SEND")
            script = emergency_script(hit.category, self.s.doctor_name, guess_language(text))
            self._send(patient.wa_id, script, patient.wa_id, action="EMERGENCY")
            self._page_doctor(f"🚨 EMERGENCY ({hit.category}) from {patient.name or patient.wa_id}:\n\"{text[:300]}\"\nMatched: '{hit.matched}'. Emergency script sent. Please call the patient now.")
            audit(self.db, "emergency", patient.wa_id, f"{hit.category}: {hit.matched}")
            return {"outcome": "emergency", "category": hit.category}

        # 6. mode off -> log only
        mode = self.mode()
        if mode == "off":
            self._store(m, "in", patient.wa_id, action="SILENT")
            return {"outcome": "silent_mode_off"}

        # 7. backoff while the doctor is active in this thread
        if patient.doctor_last_reply_at and utcnow() - as_utc(patient.doctor_last_reply_at) < timedelta(minutes=self.s.backoff_minutes):
            self._store(m, "in", patient.wa_id, action="SILENT")
            return {"outcome": "silent_backoff"}

        # 8. consent notice on first contact (sent before the answer)
        if first_contact:
            self._send(patient.wa_id, self.s.consent_notice, patient.wa_id, action="CONSENT")

        # 9. LLM
        history = [{"role": "user" if r.direction == "in" else "assistant", "content": r.body}
                   for r in recent_history(self.db, patient.wa_id) if r.body and r.direction in ("in", "out")]
        inbound_row = self._store(m, "in", patient.wa_id)
        kb_hits = self.toolbox.kb.search(text) if text else []
        ctx = AgentContext(patient_wa_id=patient.wa_id, history=history, prompt_vars=self._prompt_vars(),
                           kb_context=self.toolbox.kb.render(kb_hits), attachments=list(m.attachments))
        if m.media_type in ("image", "document") and not m.attachments:
            ctx.attachments.append(f"{m.media_type} received (media id {m.media_id}); not interpreted; attached for the doctor")
        result = self.llm.run(ctx, text or f"[{m.media_type} message]")

        if result.usage.calls:
            audit(self.db, "llm_usage", patient.wa_id, result.usage.model_dump_json())

        # 10. enforce policy on the LLM's answer (the prompt is not trusted to enforce itself)
        return self._apply(result, patient, inbound_row, text, mode)

    def _apply(self, r: AgentResult, patient: Patient, inbound: Message, text: str, mode: str) -> dict:
        inbound.classification = r.classification
        if r.classification == "EMERGENCY":
            inbound.action = "SEND"
            self.db.commit()
            self._send(patient.wa_id, emergency_script("explicit", self.s.doctor_name, guess_language(text)), patient.wa_id, action="EMERGENCY")
            self._page_doctor(f"🚨 EMERGENCY (model-detected) from {patient.wa_id}: \"{text[:300]}\"")
            audit(self.db, "emergency_model", patient.wa_id, text[:500])
            return {"outcome": "emergency", "category": "model"}

        needs_draft = r.classification == "CLINICAL" or r.action == "DRAFT_FOR_DOCTOR" or mode == "draft"
        if r.action == "SILENT" and not needs_draft:
            inbound.action = "SILENT"
            self.db.commit()
            return {"outcome": "silent"}

        if needs_draft:
            inbound.action = "DRAFT_FOR_DOCTOR"
            self.db.commit()
            if r.classification == "CLINICAL":
                # holding/intake message goes now; the clinical answer waits for the doctor.
                # If the model wanted to SEND a clinical answer directly, its text is not trusted as a holding message.
                holding = r.reply_to_patient if r.action == "DRAFT_FOR_DOCTOR" else (
                    f"Thank you for your message. Dr. {self.s.doctor_name} will see this and reply to you personally {self._eta()}.")
                self._send(patient.wa_id, holding, patient.wa_id, action="HOLDING")
                proposed = ""   # doctor writes the clinical answer (or edits the draft with E<id> text)
            else:
                proposed = r.reply_to_patient
            d = Draft(patient_wa_id=patient.wa_id, patient_text=text, proposed_reply=proposed, note_for_doctor=r.note_for_doctor)
            self.db.add(d)
            self.db.commit()
            self._page_doctor(self._format_draft(d, patient, r))
            audit(self.db, "draft_created", patient.wa_id, f"draft {d.id} ({r.classification})")
            return {"outcome": "draft", "draft_id": d.id, "classification": r.classification}

        inbound.action = "SEND"
        self.db.commit()
        self._send(patient.wa_id, r.reply_to_patient, patient.wa_id)
        return {"outcome": "sent", "classification": r.classification}

    def _format_draft(self, d: Draft, patient: Patient, r: AgentResult) -> str:
        who = patient.name or patient.wa_id
        lines = [f"📝 Draft #{d.id} [{r.classification}] from {who}", f"Patient: \"{d.patient_text[:300]}\""]
        if r.note_for_doctor:
            lines.append(f"Note: {r.note_for_doctor}")
        if d.proposed_reply:
            lines.append(f"Proposed reply: \"{d.proposed_reply}\"")
            lines.append(f"Reply A{d.id} to send, E{d.id} <your text> to send your own, X{d.id} to discard.")
        else:
            lines.append(f"Reply E{d.id} <your answer> to send it to the patient, or X{d.id} to discard.")
        return "\n".join(lines)

    # ---------- doctor commands ----------
    def handle_doctor_command(self, text: str) -> dict:
        cmd = parse_doctor_command(text)
        if not cmd:
            self._page_doctor("Commands: auto | draft | off | status | A<id> approve | E<id> <text> send your own | X<id> discard")
            return {"outcome": "doctor_unknown_command"}
        if cmd.kind == "mode":
            self.set_mode(cmd.value)
            self._page_doctor(f"Mode set to {cmd.value.upper()}.")
            audit(self.db, "mode_change", None, cmd.value)
            return {"outcome": "mode_set", "mode": cmd.value}
        if cmd.kind == "status":
            pending = self.db.scalars(select(Draft).where(Draft.status == "pending")).all()
            self._page_doctor(f"Mode: {self.mode().upper()}. Pending drafts: {len(pending)}" + ("".join(f"\n#{d.id} {d.patient_wa_id}: {d.patient_text[:60]}" for d in pending[:10])))
            return {"outcome": "status", "pending": len(pending)}
        if cmd.kind == "help":
            return self.handle_doctor_command("")
        d = self.db.get(Draft, cmd.draft_id) if cmd.draft_id else None
        if not d or d.status != "pending":
            self._page_doctor(f"Draft #{cmd.draft_id} not found or already handled.")
            return {"outcome": "draft_missing"}
        if cmd.kind == "discard":
            d.status, d.decided_at = "discarded", utcnow()
            self.db.commit()
            self._page_doctor(f"Draft #{d.id} discarded.")
            return {"outcome": "discarded", "draft_id": d.id}
        final = cmd.value if cmd.kind == "edit" else d.proposed_reply
        if not final:
            self._page_doctor(f"Draft #{d.id} has no proposed text. Use E{d.id} <your answer>.")
            return {"outcome": "needs_text", "draft_id": d.id}
        d.status, d.final_reply, d.decided_at = ("edited" if cmd.kind == "edit" else "approved"), final, utcnow()
        self.db.commit()
        p = self._patient(d.patient_wa_id)
        p.doctor_last_reply_at = utcnow()   # doctor's words -> backoff applies
        self.db.commit()
        self._send(d.patient_wa_id, final, d.patient_wa_id, action="DOCTOR_APPROVED")
        self._page_doctor(f"Sent to {d.patient_wa_id} (draft #{d.id}).")
        audit(self.db, "draft_" + d.status, d.patient_wa_id, f"draft {d.id}")
        return {"outcome": d.status, "draft_id": d.id}
