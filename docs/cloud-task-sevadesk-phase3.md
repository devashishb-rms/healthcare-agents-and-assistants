# Cloud task brief: SevaDesk Phase 3 (paste into New session → Cloud → repo devashishb-rms/healthcare-agents-and-assistants)

Build SevaDesk Phase 3 in `doctor-whatsapp-agent/` on a branch named `sevadesk-phase3` and open a pull request against `main` when done.

Context: `doctor-whatsapp-agent/` is a working MVP verified live against Claude (FastAPI webhook for Meta WhatsApp Cloud API, deterministic emergency gate in `app/safety.py`, Claude agent in `app/agent.py`, orchestrator with auto/draft/off modes and draft approval over WhatsApp in `app/orchestrator.py`, 37 passing tests with a FakeLLM). Rules that must hold: the AI never gives medical advice or prescriptions (Telemedicine Practice Guidelines 2020 cl. 5.4); CLINICAL messages are always drafts for the doctor; EMERGENCY always uses the scripted reply; every outbound message is logged; DPDP consent notice on first contact. Design doc: `docs/Healthcare AI agents build plan and prompts.md` section 1. No `ANTHROPIC_API_KEY` is available in the cloud: everything must be testable with the FakeLLM. Do not touch `ai-counsellor/` (a separate session owns it).

Deliverables:
1. Doctor web console: minimal server-rendered UI (FastAPI + Jinja2, no JS framework) at `/console`, protected by `CONSOLE_TOKEN` from `.env`: pending drafts with approve/edit/discard forms, mode switch, per-patient conversation view, today's emergency pages, and a usage/cost page summarising `llm_usage` audit rows per day and per patient (tokens and estimated USD from a small per-model price table).
2. Appointment reminders: `python -m app.reminders` finds next-day bookings in `data/calendar.json` and sends a WhatsApp template message (add `WhatsAppClient.send_template(to, template_name, language, components)`) only to patients with `consent_at` set and `opted_out = 0`; dry-run prints. README: templates need Meta approval and opt-in.
3. Postgres readiness: SQLAlchemy works with `DATABASE_URL=postgresql+psycopg://...` (add `psycopg[binary]`), SQLite stays default, add `requirements.txt`.
4. Webhook hardening: reject payloads whose `phone_number_id` does not match `WHATSAPP_PHONE_NUMBER_ID` (when set), log and ignore status webhooks, tests for signature verification (valid, missing, bad).
5. Keep all existing tests passing; add tests for console auth, reminders (dry-run, respects consent/opt-out), and the phone_number_id check. Update README.

Done means: `pytest -q` passes in `doctor-whatsapp-agent/` (python3 -m venv .venv; pip install -r requirements.txt), the console renders in dry-run, and a PR is open describing what was added and what still needs real Meta credentials.
