"""Next-day reminders: only consenting, not-opted-out patients; dry-run prints and writes nothing."""
import json
from datetime import date, timedelta

from app import reminders
from app.db import AuditLog, Message, Patient, utcnow
from app.reminders import bookings_on, send_reminders
from app.tools import Calendar

TOMORROW = date.today() + timedelta(days=1)
DAY_AFTER = TOMORROW + timedelta(days=1)
CONSENTED, CONSENTED2, NO_CONSENT, OPTED_OUT, UNKNOWN = "919900000001", "919900000002", "919900000003", "919900000004", "919900000005"


def _calendar(tmp_path):
    def slot(day, hhmm, who, name=None):
        return {"id": f"{day}-{hhmm}", "start": f"{day.isoformat()}T{hhmm[:2]}:{hhmm[2:]}", "booked_by": who, "patient_name": name}
    data = {"doctor_status": "in OPD", "busy_until": None, "slots": [
        slot(TOMORROW, "1000", CONSENTED, "Rahul"),
        slot(TOMORROW, "1700", CONSENTED),                 # same patient twice -> one reminder listing both
        slot(TOMORROW, "1020", NO_CONSENT, "Asha"),
        slot(TOMORROW, "1040", OPTED_OUT, "Vikram"),
        slot(TOMORROW, "1100", UNKNOWN, "Ghost"),
        slot(TOMORROW, "1120", None),                      # free
        slot(DAY_AFTER, "1000", CONSENTED2, "Meena"),      # not tomorrow
    ]}
    p = tmp_path / "rem.json"
    p.write_text(json.dumps(data))
    return Calendar(str(p))


def _seed(db):
    now = utcnow()
    db.add_all([
        Patient(wa_id=CONSENTED, name="Rahul K", consent_sent_at=now, consent_at=now),
        Patient(wa_id=CONSENTED2, name="Meena", consent_sent_at=now, consent_at=now),
        Patient(wa_id=NO_CONSENT, consent_sent_at=now, consent_at=None),
        Patient(wa_id=OPTED_OUT, consent_sent_at=now, consent_at=now, opted_out=1),
    ])
    db.commit()


def test_bookings_on_groups_by_patient(tmp_path):
    b = bookings_on(_calendar(tmp_path), TOMORROW)
    assert set(b) == {CONSENTED, NO_CONSENT, OPTED_OUT, UNKNOWN}
    assert [s["start"][-5:] for s in b[CONSENTED]] == ["10:00", "17:00"]


def test_dry_run_plans_but_sends_and_writes_nothing(env, tmp_path):
    _seed(env.db)
    plans = send_reminders(env.settings, env.db, env.wa, _calendar(tmp_path), TOMORROW, dry_run=True)
    by = {p.patient_wa_id: p for p in plans}
    assert by[CONSENTED].status == "planned" and by[CONSENTED].patient_name == "Rahul"
    assert by[NO_CONSENT].status == "skipped_no_consent"
    assert by[OPTED_OUT].status == "skipped_opted_out"
    assert by[UNKNOWN].status == "skipped_unknown_patient"
    assert CONSENTED2 not in by
    assert env.wa.sent == []
    assert env.db.query(Message).count() == 0 and env.db.query(AuditLog).count() == 0


def test_live_run_sends_template_only_to_consenting_patients(env, tmp_path):
    _seed(env.db)
    plans = send_reminders(env.settings, env.db, env.wa, _calendar(tmp_path), TOMORROW, dry_run=False)
    sent = [s for s in env.wa.sent if "template" in s]
    assert len(sent) == 1 and sent[0]["to"] == CONSENTED
    assert sent[0]["template"] == env.settings.reminder_template_name and sent[0]["language"] == env.settings.reminder_template_language
    params = [p["text"] for p in sent[0]["components"][0]["parameters"]]
    assert params[0] == "Rahul" and params[1] == "Dr. Mehta" and "10:00 AM" in params[2] and "5:00 PM" in params[2] and params[3] == env.settings.clinic_name
    assert {p.status for p in plans} == {"sent", "skipped_no_consent", "skipped_opted_out", "skipped_unknown_patient"}
    out = env.db.query(Message).filter_by(direction="out", action="REMINDER").all()
    assert len(out) == 1 and out[0].patient_wa_id == CONSENTED and "reminder" in out[0].body
    assert env.db.query(AuditLog).filter_by(event="reminder_sent", patient_wa_id=CONSENTED).count() == 1


def test_send_failure_is_logged_and_does_not_stop_the_run(env, tmp_path, monkeypatch):
    _seed(env.db)
    env.db.add(Patient(wa_id=UNKNOWN, consent_sent_at=utcnow(), consent_at=utcnow()))
    env.db.commit()

    def boom(to, *a, **k):
        if to == CONSENTED:
            raise RuntimeError("131047 re-engagement")
        return {"ok": True}
    monkeypatch.setattr(env.wa, "send_template", boom)
    plans = {p.patient_wa_id: p for p in send_reminders(env.settings, env.db, env.wa, _calendar(tmp_path), TOMORROW, dry_run=False)}
    assert plans[CONSENTED].status == "failed" and plans[UNKNOWN].status == "sent"
    assert env.db.query(AuditLog).filter_by(event="reminder_failed").count() == 1


def test_cli_dry_run_prints_plan(env, tmp_path, monkeypatch, capsys):
    _seed(env.db)
    env.db.close()
    cal = _calendar(tmp_path)
    monkeypatch.setattr(env.settings, "calendar_path", str(cal.path))
    monkeypatch.setattr(reminders, "get_settings", lambda: env.settings)
    assert reminders.main(["--dry-run", "--date", TOMORROW.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and TOMORROW.isoformat() in out
    assert "planned" in out and "skipped_opted_out" in out and "skipped_no_consent" in out
    assert CONSENTED in out and CONSENTED2 not in out
