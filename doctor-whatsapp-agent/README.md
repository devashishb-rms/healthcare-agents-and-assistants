# SevaDesk – the doctor's WhatsApp front-desk agent (MVP)

Answers patient messages on a doctor's WhatsApp number while the doctor is busy: handles appointments, timings, fees,
reports-ready status and reassurance on its own; collects intake for clinical questions and hands them to the doctor as
**drafts**; and fires a scripted emergency response (108/112, Tele-MANAS 14416 for self-harm) **before any AI runs**.

Design and rationale: `../docs/Healthcare AI agents build plan and prompts.md`, section 1.

## How it is wired

```
Patient WhatsApp -> Meta Cloud API webhook -> POST /webhook (signature check, dedupe, 200 fast)
   -> Orchestrator.handle()  [app/orchestrator.py]
        1 dedupe  2 doctor-app echo -> backoff  3 doctor commands  4 consent / STOP
        5 EMERGENCY regex gate (EN / Hinglish / Devanagari)  [app/safety.py]   <- no LLM involved
        6 mode off  7 backoff while doctor is active  8 consent notice on first contact
        9 Claude agent with tools (slots, booking, report status, clinic KB)  [app/agent.py, app/tools.py]
       10 policy enforcement: CLINICAL is ALWAYS a draft, EMERGENCY ALWAYS uses the script
   -> WhatsApp replies to the patient; drafts and pages go to DOCTOR_CONTROL_NUMBER
```

Doctor controls everything from WhatsApp (from `DOCTOR_CONTROL_NUMBER`):

| Send | Effect |
|---|---|
| `auto` | admin/social replies go out immediately; clinical -> draft |
| `draft` | nothing goes out without approval (patient still gets an acknowledgement) |
| `off` | log only |
| `status` | mode + pending drafts |
| `A12` | approve draft 12 (sends the proposed reply) |
| `E12 your text` | send your own words for draft 12 (this is how clinical answers go out) |
| `X12` | discard |

The same actions exist over HTTP: `GET /drafts`, `POST /drafts/{id}` `{"action":"approve|edit|discard","text":"..."}`, `POST /mode/{auto|draft|off}`.

## Run it locally (no WhatsApp needed)

```bash
cp .env.example .env             # ANTHROPIC_WORKSPACE_ID is needed only for an org-level key
.venv/bin/python seed_calendar.py   # generate upcoming slots            # fill ANTHROPIC_API_KEY (or run `ant auth login`); keep DRY_RUN=true
.venv/bin/python -m pytest -q   # 37 tests, no network
.venv/bin/python simulate.py    # chat as a patient; add --doctor to act as the doctor
.venv/bin/uvicorn app.main:app --reload --port 8000   # then POST /simulate {"from_wa_id":"9199...","text":"..."}
```

In dry-run mode every outbound WhatsApp message is printed instead of sent.

## Go live (pilot doctor)

1. Meta for Developers: create an app, add WhatsApp, verify the business.
2. Onboard the doctor's number with **Coexistence** (WhatsApp Business app stays usable; app replies arrive as `message_echoes`).
   Subscribe the webhook to `messages` and `message_echoes`.
3. Expose `POST /webhook` over HTTPS (ngrok for the pilot), set `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`,
   `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `DOCTOR_CONTROL_NUMBER`, the clinic identity fields, and `DRY_RUN=false`.
4. Edit `data/clinic_kb.json` (doctor-written FAQs) and `data/reports.json`; run `.venv/bin/python seed_calendar.py` to generate a week of slots (re-run weekly, or replace with your PMS).
5. Optional: `SARVAM_API_KEY` for Hindi/regional voice-note transcription.

## Models and cost

`AGENT_MODEL` defaults to `claude-opus-5-5` at `AGENT_EFFORT=low`; switch to `claude-sonnet-5-5` or `claude-haiku-5-5`
for routine traffic once the pilot shows draft-acceptance is stable (see unit economics in the research report).
The system prompt is cached (`cache_control`), the final answer is schema-constrained JSON, and tools are `strict`.
Every LLM call's token usage is written to the `audit_log` table (event `llm_usage`) for per-patient and per-doctor cost accounting.
`ENABLE_FALLBACKS=true` turns on Anthropic's server-side refusal fallback (beta); it is off by default because the
orchestrator already converts any refusal into a draft for the doctor.

## What is deliberately NOT here yet

- Web console UI (drafts are handled over WhatsApp or the JSON endpoints)
- Postgres / Redis queue (FastAPI background tasks + SQLite are enough for one clinic)
- Clinic PMS / Google Calendar integration (JSON slot store for now)
- WhatsApp templates for business-initiated reminders (requires opt-in + template approval)
- Fine-tuned classifier; the regex gate + Claude classification are the MVP
