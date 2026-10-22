from datetime import timedelta

from app.agent import AgentResult
from app.db import Draft, Message, utcnow
from app.orchestrator import Inbound
from tests.conftest import DOCTOR, PATIENT


def msg(text, mid=None, sender=PATIENT, **kw):
    import uuid
    return Inbound(wa_message_id=mid or f"m-{uuid.uuid4()}", from_wa_id=sender, text=text, **kw)


def outbound(env, to):
    return [s["text"] for s in env.wa.sent if s["to"] == to]


def test_first_contact_sends_consent_then_answer(env):
    r = env.orch.handle(msg("Is the clinic open on Sunday?"))
    assert r["outcome"] == "sent"
    out = outbound(env, PATIENT)
    assert len(out) == 2 and "AI assistant" in out[0] and "open" in out[1]
    assert len(env.llm.calls) == 1


def test_duplicate_webhook_is_ignored(env):
    env.orch.handle(msg("hello", mid="dup-1"))
    assert env.orch.handle(msg("hello", mid="dup-1"))["outcome"] == "duplicate"
    assert len(env.llm.calls) == 1


def test_emergency_bypasses_llm_and_pages_doctor(env):
    r = env.orch.handle(msg("I don't want to live anymore"))
    assert r["outcome"] == "emergency" and r["category"] == "self_harm"
    assert env.llm.calls == []
    patient_out = outbound(env, PATIENT)
    assert any("14416" in t and "108" in t for t in patient_out)
    assert any("EMERGENCY" in t for t in outbound(env, DOCTOR))


def test_hinglish_emergency(env):
    r = env.orch.handle(msg("papa ko seene me dard hai aur saans nahi aa rahi"))
    assert r["outcome"] == "emergency"
    assert any("108" in t for t in outbound(env, PATIENT))


def test_clinical_creates_draft_and_holding_message(env):
    env.llm.script["bukhar"] = AgentResult(
        classification="CLINICAL", action="DRAFT_FOR_DOCTOR",
        reply_to_patient="Main samajh sakti hoon. Dr. Mehta 1 pm tak jawab denge. Bachhe ki umar kya hai?",
        note_for_doctor="Child fever 102F since yesterday; asking what to give.")
    r = env.orch.handle(msg("Bachhe ko 102 bukhar hai kal se, kya dun?"))
    assert r["outcome"] == "draft" and r["classification"] == "CLINICAL"
    assert any("umar" in t for t in outbound(env, PATIENT))          # holding/intake message sent now
    d = env.db.get(Draft, r["draft_id"])
    assert d.status == "pending" and d.proposed_reply == ""           # doctor must supply the clinical answer
    assert any(f"Draft #{d.id}" in t and "Child fever" in t for t in outbound(env, DOCTOR))


def test_llm_cannot_send_clinical_even_if_it_says_send(env):
    env.llm.script["paracetamol"] = AgentResult(classification="CLINICAL", action="SEND", reply_to_patient="Take 500mg twice daily.", note_for_doctor="")
    r = env.orch.handle(msg("can I take paracetamol?"))
    assert r["outcome"] == "draft"
    assert not any("500mg" in t for t in outbound(env, PATIENT))


def test_model_emergency_classification_uses_script(env):
    env.llm.script["weird"] = AgentResult(classification="EMERGENCY", action="SEND", reply_to_patient="(model text)", note_for_doctor="")
    r = env.orch.handle(msg("something weird is happening to my body"))
    assert r["outcome"] == "emergency"
    assert any("108" in t for t in outbound(env, PATIENT)) and not any("(model text)" in t for t in outbound(env, PATIENT))


def test_doctor_approves_draft_via_whatsapp(env):
    env.llm.script["fee"] = AgentResult(classification="ADMIN", action="SEND", reply_to_patient="Consultation fee is ₹600.", note_for_doctor="")
    env.orch.handle(msg("draft", sender=DOCTOR))            # switch to draft mode
    r = env.orch.handle(msg("what is the fee?"))
    assert r["outcome"] == "draft"
    assert not any("₹600" in t for t in outbound(env, PATIENT))
    env.wa.sent.clear()
    r2 = env.orch.handle(msg(f"A{r['draft_id']}", sender=DOCTOR))
    assert r2["outcome"] == "approved"
    assert any("₹600" in t for t in outbound(env, PATIENT))
    assert env.db.get(Draft, r["draft_id"]).status == "approved"


def test_doctor_edit_sends_own_text_and_triggers_backoff(env):
    env.llm.script["bukhar"] = AgentResult(classification="CLINICAL", action="DRAFT_FOR_DOCTOR", reply_to_patient="Noted, doctor will reply.", note_for_doctor="fever")
    r = env.orch.handle(msg("bukhar hai"))
    env.orch.handle(msg(f"E{r['draft_id']} Give paracetamol syrup 5ml if fever above 100F, see me at 5pm.", sender=DOCTOR))
    assert any("paracetamol syrup" in t for t in outbound(env, PATIENT))
    env.wa.sent.clear()
    r3 = env.orch.handle(msg("ok thank you doctor"))        # doctor just replied -> agent stays silent
    assert r3["outcome"] == "silent_backoff" and outbound(env, PATIENT) == []


def test_echo_from_doctor_app_triggers_backoff(env):
    env.orch.handle(Inbound(wa_message_id="e1", from_wa_id="BUSINESS", to_wa_id=PATIENT, text="Aao 5 baje", is_echo=True))
    r = env.orch.handle(msg("theek hai"))
    assert r["outcome"] == "silent_backoff"
    assert env.llm.calls == []


def test_mode_off_logs_only(env):
    env.orch.handle(msg("off", sender=DOCTOR))
    r = env.orch.handle(msg("hello?"))
    assert r["outcome"] == "silent_mode_off" and env.llm.calls == []
    assert env.db.query(Message).filter_by(patient_wa_id=PATIENT).count() == 1


def test_opt_out(env):
    env.orch.handle(msg("STOP"))
    env.wa.sent.clear()
    r = env.orch.handle(msg("hi again"))
    assert r["outcome"] == "silent_opted_out" and outbound(env, PATIENT) == []


def test_emergency_still_fires_while_backoff(env):
    p = env.orch._patient(PATIENT)
    p.doctor_last_reply_at = utcnow() - timedelta(minutes=1)
    env.db.commit()
    r = env.orch.handle(msg("he is unconscious and not responding"))
    assert r["outcome"] == "emergency"


def test_status_and_unknown_commands(env):
    assert env.orch.handle(msg("status", sender=DOCTOR))["outcome"] == "status"
    assert env.orch.handle(msg("blah", sender=DOCTOR))["outcome"] == "doctor_unknown_command"
    assert env.orch.handle(msg("A999", sender=DOCTOR))["outcome"] == "draft_missing"
