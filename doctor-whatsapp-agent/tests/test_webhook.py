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
