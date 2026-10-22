"""Doctor web console: auth, draft actions, mode switch, patient view, emergencies, usage/cost page."""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import main
from app.agent import AgentResult, Usage
from app.db import AuditLog, Base, Draft, Message, utcnow
from app.pricing import PRICES_USD_PER_MTOK, estimate_usd
from tests.conftest import FakeLLM, PATIENT

TOKEN = "test-console-token"
AUTH = {"X-Console-Token": TOKEN}


@pytest.fixture
def client(monkeypatch):
    with main.SessionLocal() as db:                         # the app DB is shared across tests: start clean
        for t in reversed(Base.metadata.sorted_tables):
            db.execute(delete(t))
        db.commit()
    monkeypatch.setattr(main.settings, "console_token", TOKEN)
    monkeypatch.setattr(main, "llm", FakeLLM())
    main.wa.sent.clear()
    return TestClient(main.app, follow_redirects=False)


def simulate(client, text, sender=PATIENT):
    r = client.post("/simulate", json={"from_wa_id": sender, "text": text})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def outbound(to):
    return [s["text"] for s in main.wa.sent if s["to"] == to and "text" in s]


# ---------------- auth ----------------
def test_console_requires_token(client):
    r = client.get("/console")
    assert r.status_code == 303 and r.headers["location"] == "/console/login"
    assert client.get("/console/usage").status_code == 303
    assert client.get("/console", headers={"X-Console-Token": "nope"}).status_code == 403
    assert client.get("/console", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert client.post("/console/mode", data={"mode": "off"}).status_code == 303      # redirected to login, not applied
    assert client.get("/console", headers=AUTH).status_code == 200
    assert client.get("/console", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_console_login_form_sets_cookie(client):
    assert client.get("/console/login").status_code == 200
    bad = client.post("/console/login", data={"token": "wrong"})
    assert bad.status_code == 303 and "error=1" in bad.headers["location"]
    good = client.post("/console/login", data={"token": TOKEN})
    assert good.status_code == 303 and good.headers["location"] == "/console"
    assert "console_token" in good.cookies
    client.cookies.set("console_token", TOKEN)
    assert client.get("/console").status_code == 200
    out = client.post("/console/logout")
    assert out.status_code == 303
    client.cookies.clear()
    assert client.get("/console").status_code == 303


def test_console_disabled_without_token_setting(client, monkeypatch):
    monkeypatch.setattr(main.settings, "console_token", "")
    assert client.get("/console", headers=AUTH).status_code == 503
    assert client.get("/console/login").status_code == 503


# ---------------- drafts ----------------
def test_dashboard_lists_and_sends_clinical_draft(client):
    main.llm.script["bukhar"] = AgentResult(classification="CLINICAL", action="DRAFT_FOR_DOCTOR",
                                            reply_to_patient="Doctor will reply by 1 pm. Bachhe ki umar?", note_for_doctor="Child fever since yesterday")
    r = simulate(client, "Bachhe ko bukhar hai")
    assert r["outcome"] == "draft"
    page = client.get("/console", headers=AUTH)
    assert page.status_code == 200
    assert f"Draft #{r['draft_id']}" in page.text and "Child fever since yesterday" in page.text and "Bachhe ko bukhar hai" in page.text
    assert "Send as proposed" not in page.text            # clinical: the doctor must write the reply
    main.wa.sent.clear()
    # edit without text -> nothing sent
    r2 = client.post(f"/console/drafts/{r['draft_id']}", data={"action": "edit", "text": "  "}, headers=AUTH)
    assert r2.status_code == 303 and outbound(PATIENT) == []
    r3 = client.post(f"/console/drafts/{r['draft_id']}", data={"action": "edit", "text": "Give syrup 5ml, see me at 5."}, headers=AUTH)
    assert r3.status_code == 303 and "edited" in r3.headers["location"]
    assert outbound(PATIENT) == ["Give syrup 5ml, see me at 5."]
    with main.SessionLocal() as db:
        d = db.get(Draft, r["draft_id"])
        assert d.status == "edited" and d.final_reply.startswith("Give syrup")
        assert db.query(Message).filter_by(patient_wa_id=PATIENT, direction="out", action="DOCTOR_APPROVED").count() == 1
    assert "Draft #" not in client.get("/console", headers=AUTH).text.split("Emergency pages")[0]


def test_dashboard_approve_and_discard_admin_drafts(client):
    main.llm.script["fee"] = AgentResult(classification="ADMIN", action="SEND", reply_to_patient="Fee is ₹600.", note_for_doctor="")
    assert client.post("/console/mode", data={"mode": "draft"}, headers=AUTH).status_code == 303
    a = simulate(client, "what is the fee?")
    b = simulate(client, "fee please", sender="919999900002")
    assert a["outcome"] == b["outcome"] == "draft"
    page = client.get("/console", headers=AUTH).text
    assert "Send as proposed" in page and "Fee is ₹600." in page
    main.wa.sent.clear()
    client.post(f"/console/drafts/{a['draft_id']}", data={"action": "approve"}, headers=AUTH)
    client.post(f"/console/drafts/{b['draft_id']}", data={"action": "discard"}, headers=AUTH)
    assert outbound(PATIENT) == ["Fee is ₹600."] and outbound("919999900002") == []
    with main.SessionLocal() as db:
        assert db.get(Draft, a["draft_id"]).status == "approved" and db.get(Draft, b["draft_id"]).status == "discarded"
    bad = client.post(f"/console/drafts/{a['draft_id']}", data={"action": "approve"}, headers=AUTH)
    assert "draft_missing" in bad.headers["location"]
    assert client.post(f"/console/drafts/{a['draft_id']}", data={"action": "fly"}, headers=AUTH).status_code == 400


def test_mode_switch(client):
    r = client.post("/console/mode", data={"mode": "off"}, headers=AUTH)
    assert r.status_code == 303 and "Mode+set+to+off" in r.headers["location"]
    assert ">OFF<" in client.get("/console", headers=AUTH).text
    assert simulate(client, "hello?")["outcome"] == "silent_mode_off"
    assert client.post("/console/mode", data={"mode": "silent"}, headers=AUTH).status_code == 400
    client.post("/console/mode", data={"mode": "auto"}, headers=AUTH)
    assert simulate(client, "is the clinic open?")["outcome"] == "sent"


# ---------------- patient view / emergencies ----------------
def test_patient_conversation_view(client):
    simulate(client, "is the clinic open on sunday?")
    page = client.get(f"/console/patients/{PATIENT}", headers=AUTH)
    assert page.status_code == 200
    assert "is the clinic open on sunday?" in page.text and "AI assistant" in page.text and "open 10-1" in page.text
    assert "notice sent" in page.text
    assert client.get("/console/patients/000", headers=AUTH).status_code == 404


def test_dashboard_shows_todays_emergencies_only(client):
    r = simulate(client, "papa ko seene me dard hai aur saans nahi aa rahi")
    assert r["outcome"] == "emergency"
    with main.SessionLocal() as db:
        old = AuditLog(event="emergency", patient_wa_id="919999900077", detail="self_harm: old", created_at=utcnow() - timedelta(days=2))
        db.add(old)
        db.commit()
    page = client.get("/console", headers=AUTH).text
    assert "cardiac_respiratory" in page and "keyword gate" in page
    assert "919999900077" not in page.split("Recent patients")[0]


# ---------------- usage / cost ----------------
def test_usage_page_sums_tokens_and_cost(client):
    main.llm.default = AgentResult(classification="ADMIN", action="SEND", reply_to_patient="Open 10-1.",
                                   usage=Usage(model="claude-haiku-5-5", input_tokens=5000, output_tokens=150, cache_read_input_tokens=2000, calls=1))
    simulate(client, "timings?")
    simulate(client, "timings again?")
    simulate(client, "fees?", sender="919999900002")
    with main.SessionLocal() as db:       # a legacy row without a model -> priced as AGENT_MODEL and flagged
        db.add(AuditLog(event="llm_usage", patient_wa_id="919999900003", detail=json.dumps({"input_tokens": 1000, "output_tokens": 100, "calls": 1})))
        db.add(AuditLog(event="llm_usage", patient_wa_id="919999900004", detail=json.dumps({"model": "claude-opus-5-5", "input_tokens": 1000, "output_tokens": 100, "calls": 2}),
                        created_at=utcnow() - timedelta(days=40)))     # outside the 30-day window
        db.commit()
    page = client.get("/console/usage", headers=AUTH)
    assert page.status_code == 200
    haiku = 3 * estimate_usd("claude-haiku-5-5", 5000, 150, 2000, 0)
    legacy = estimate_usd(main.settings.agent_model, 1000, 100)
    assert f"${haiku + legacy:,.4f}" in page.text
    assert "claude-haiku-5-5" in page.text and "919999900003" in page.text and "919999900004" not in page.text
    assert "predate per-model accounting" in page.text and f"{3 * 7150 + 1100:,}" in page.text
    year = client.get("/console/usage?days=365", headers=AUTH).text
    assert "919999900004" in year
    assert all(m in page.text for m in PRICES_USD_PER_MTOK)
