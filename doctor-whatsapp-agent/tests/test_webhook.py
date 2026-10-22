from app.main import parse_webhook


def test_parse_text_and_echo():
    payload = {"entry": [{"changes": [
        {"field": "messages", "value": {"contacts": [{"wa_id": "919999900001", "profile": {"name": "Rahul"}}],
                                        "messages": [{"id": "wamid.1", "from": "919999900001", "type": "text", "text": {"body": "hi"}},
                                                     {"id": "wamid.2", "from": "919999900001", "type": "audio", "audio": {"id": "media9"}}]}},
        {"field": "message_echoes", "value": {"message_echoes": [{"id": "wamid.3", "from": "91BUSINESS", "to": "919999900001", "type": "text", "text": {"body": "Aao 5 baje"}}]}},
    ]}]}
    items = parse_webhook(payload)
    assert [i.wa_message_id for i in items] == ["wamid.1", "wamid.2", "wamid.3"]
    assert items[0].text == "hi" and "Rahul" in items[0].attachments[0]
    assert items[1].media_type == "audio" and items[1].media_id == "media9"
    assert items[2].is_echo and items[2].to_wa_id == "919999900001"


# ---------------------------------------------------------------------------------------------
# Hardening: signature verification, phone_number_id check, status webhooks
# ---------------------------------------------------------------------------------------------
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import main


def _payload(phone_number_id="123456", text="hello", from_wa="919999900055", mid="wamid.x1"):
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "9100000", "phone_number_id": phone_number_id},
        "contacts": [{"wa_id": from_wa, "profile": {"name": "Test"}}],
        "messages": [{"id": mid, "from": from_wa, "timestamp": "1", "type": "text", "text": {"body": text}}]}}]}]}


def _status_payload(phone_number_id="123456"):
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "9100000", "phone_number_id": phone_number_id},
        "statuses": [{"id": "wamid.out1", "status": "delivered", "timestamp": "1", "recipient_id": "919999900055"}]}}]}]}


@pytest.fixture
def client(monkeypatch):
    processed = []
    monkeypatch.setattr(main, "process", lambda m: processed.append(m))   # background task target; never hits the LLM
    c = TestClient(main.app)
    c.processed = processed
    return c


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_valid_missing_bad(client, monkeypatch):
    monkeypatch.setattr(main.settings, "whatsapp_app_secret", "topsecret")
    body = json.dumps(_payload()).encode()
    ok = client.post("/webhook", content=body, headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sig("topsecret", body)})
    assert ok.status_code == 200 and len(client.processed) == 1
    missing = client.post("/webhook", content=body, headers={"Content-Type": "application/json"})
    assert missing.status_code == 403 and "missing" in missing.json()["detail"]
    bad = client.post("/webhook", content=body, headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sig("wrong", body)})
    assert bad.status_code == 403 and "bad" in bad.json()["detail"]
    tampered = client.post("/webhook", content=body + b" ", headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sig("topsecret", body)})
    assert tampered.status_code == 403
    assert len(client.processed) == 1                     # only the valid one was processed


def test_no_app_secret_skips_signature_check(client, monkeypatch):
    monkeypatch.setattr(main.settings, "whatsapp_app_secret", "")
    assert client.post("/webhook", json=_payload()).status_code == 200


def test_phone_number_id_mismatch_rejected(client, monkeypatch):
    monkeypatch.setattr(main.settings, "whatsapp_phone_number_id", "123456")
    assert client.post("/webhook", json=_payload(phone_number_id="123456")).status_code == 200
    r = client.post("/webhook", json=_payload(phone_number_id="999999"))
    assert r.status_code == 403 and "phone_number_id" in r.json()["detail"]
    assert len(client.processed) == 1


def test_phone_number_id_check_off_when_unset(client, monkeypatch):
    monkeypatch.setattr(main.settings, "whatsapp_phone_number_id", "")
    assert client.post("/webhook", json=_payload(phone_number_id="anything")).status_code == 200
    assert len(client.processed) == 1


def test_status_webhook_logged_and_ignored(client, monkeypatch, caplog):
    monkeypatch.setattr(main.settings, "whatsapp_phone_number_id", "123456")
    with caplog.at_level("INFO", logger="sevadesk"):
        r = client.post("/webhook", json=_status_payload())
    assert r.status_code == 200
    assert client.processed == []
    assert any("status update" in rec.getMessage() and "delivered" in rec.getMessage() for rec in caplog.records)
    assert main.status_updates(_status_payload())[0]["status"] == "delivered"
    assert main.parse_webhook(_status_payload()) == []


def test_non_object_payload_rejected(client):
    assert client.post("/webhook", json=[1, 2, 3]).status_code == 400
