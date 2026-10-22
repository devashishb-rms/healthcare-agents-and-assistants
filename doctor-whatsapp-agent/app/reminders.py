"""Next-day appointment reminders via WhatsApp template messages.

    python -m app.reminders              # send reminders for tomorrow's bookings (dry-run unless DRY_RUN=false)
    python -m app.reminders --dry-run    # print what would be sent, never call WhatsApp, write nothing to the DB
    python -m app.reminders --date 2026-10-25

Business-initiated messages (outside the 24-hour customer-service window) MUST use a Meta-approved template and MAY
only go to patients who opted in (DPDP consent). Enforced here, not left to the caller:
  - the slot must be booked (`booked_by`) and start on the target date;
  - the patient row must have `consent_at` set and `opted_out = 0`;
  - one reminder per patient per run (a patient with two slots gets one message listing both times).
Every real send is logged to `messages` (action REMINDER) and `audit_log` (reminder_sent)."""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import Message, Patient, audit, make_session_factory
from .tools import Calendar
from .whatsapp import WhatsAppClient

log = logging.getLogger("sevadesk.reminders")


@dataclass
class ReminderPlan:
    patient_wa_id: str
    patient_name: Optional[str]
    slot_starts: list[str] = field(default_factory=list)   # ISO "YYYY-MM-DDTHH:MM"
    status: str = "planned"       # planned | sent | skipped_no_consent | skipped_opted_out | skipped_unknown_patient | failed
    detail: str = ""


def bookings_on(calendar: Calendar, on: date) -> dict[str, list[dict]]:
    """Booked slots grouped by patient wa_id for the given date."""
    out: dict[str, list[dict]] = {}
    prefix = on.isoformat()
    for s in calendar.data.get("slots", []):
        if s.get("booked_by") and str(s.get("start", "")).startswith(prefix):
            out.setdefault(s["booked_by"], []).append(s)
    for slots in out.values():
        slots.sort(key=lambda s: s["start"])
    return out


def _fmt_times(starts: list[str]) -> str:
    times = []
    for st in starts:
        try:
            times.append(datetime.fromisoformat(st).strftime("%-d %b %Y, %-I:%M %p"))
        except ValueError:
            times.append(st)
    return " and ".join(times)


def build_components(settings: Settings, name: Optional[str], starts: list[str]) -> list[dict]:
    """Body parameters {{1}} patient name, {{2}} doctor, {{3}} appointment time(s), {{4}} clinic name.
    The approved template must have exactly these four body placeholders (see README)."""
    return [{"type": "body", "parameters": [
        {"type": "text", "text": name or "there"},
        {"type": "text", "text": f"Dr. {settings.doctor_name}"},
        {"type": "text", "text": _fmt_times(starts)},
        {"type": "text", "text": settings.clinic_name},
    ]}]


def send_reminders(settings: Settings, db: Session, wa: WhatsAppClient, calendar: Calendar,
                   on: date, dry_run: bool) -> list[ReminderPlan]:
    """Plan and (unless dry_run) send one reminder per consenting, not-opted-out patient booked on `on`."""
    plans: list[ReminderPlan] = []
    for wa_id, slots in bookings_on(calendar, on).items():
        name = next((s.get("patient_name") for s in slots if s.get("patient_name")), None)
        plan = ReminderPlan(patient_wa_id=wa_id, patient_name=name, slot_starts=[s["start"] for s in slots])
        patient = db.get(Patient, wa_id)
        if patient is None:
            plan.status, plan.detail = "skipped_unknown_patient", "no patient record (never messaged the clinic)"
        elif patient.opted_out:
            plan.status, plan.detail = "skipped_opted_out", "patient sent STOP"
        elif patient.consent_at is None:
            plan.status, plan.detail = "skipped_no_consent", "consent not recorded yet"
        else:
            plan.patient_name = plan.patient_name or patient.name
            components = build_components(settings, plan.patient_name, plan.slot_starts)
            if dry_run:
                plan.status, plan.detail = "planned", f"template {settings.reminder_template_name} ({settings.reminder_template_language})"
            else:
                try:
                    wa.send_template(wa_id, settings.reminder_template_name, settings.reminder_template_language, components)
                    body = f"[template {settings.reminder_template_name}] reminder for {_fmt_times(plan.slot_starts)}"
                    db.add(Message(patient_wa_id=wa_id, direction="out", body=body, action="REMINDER"))
                    db.commit()
                    audit(db, "reminder_sent", wa_id, ", ".join(plan.slot_starts))
                    plan.status, plan.detail = "sent", body
                except Exception as e:  # noqa: BLE001 - keep going for the other patients
                    log.error("reminder to %s failed: %s", wa_id, e)
                    audit(db, "reminder_failed", wa_id, str(e)[:500])
                    plan.status, plan.detail = "failed", str(e)
        plans.append(plan)
    return plans


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Send next-day appointment reminders over WhatsApp templates.")
    ap.add_argument("--date", help="YYYY-MM-DD (default: tomorrow)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; send nothing; write nothing")
    args = ap.parse_args(argv)
    settings = get_settings()
    on = date.fromisoformat(args.date) if args.date else date.today() + timedelta(days=1)
    dry_run = args.dry_run or settings.dry_run
    wa = WhatsAppClient(settings.whatsapp_token, settings.whatsapp_phone_number_id, settings.whatsapp_api_version, dry_run=settings.dry_run)
    calendar = Calendar(settings.calendar_path)
    SessionLocal = make_session_factory(settings.database_url)
    with SessionLocal() as db:
        plans = send_reminders(settings, db, wa, calendar, on, dry_run=dry_run)
    print(f"Reminders for {on.isoformat()} ({'DRY RUN' if dry_run else 'LIVE'}): {len(plans)} booked patient(s)")
    for p in plans:
        print(f"  {p.patient_wa_id:>15}  {p.patient_name or '-':<20} {', '.join(p.slot_starts):<40} {p.status}  {p.detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
