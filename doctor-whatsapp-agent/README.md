# SevaDesk – the doctor's WhatsApp front-desk agent (MVP + Phase 3)

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

The same actions exist over HTTP: `GET /drafts`, `POST /drafts/{id}` `{"action":"approve|edit|discard","text":"..."}`, `POST /mode/{auto|draft|off}`,
and in the **doctor web console** at `/console` (below).

## Doctor web console (`/console`)

Server-rendered pages (FastAPI + Jinja2, no JavaScript framework), protected by `CONSOLE_TOKEN` from `.env`.
With the token empty the console is disabled (HTTP 503), not open. Sign in at `/console/login` (sets an HttpOnly,
SameSite=Lax cookie for 12 hours), or send `X-Console-Token: <token>` / `Authorization: Bearer <token>` from curl.

| Page | What it shows |
|---|---|
| `/console` | pending drafts with **Send as proposed / Send my text / Discard** forms (clinical drafts have no proposed text: you write the reply), the **auto / draft / off** mode switch, today's emergency pages, recent patients |
| `/console/patients/{wa_id}` | the full conversation (patient, assistant, your own app replies), consent/opt-out state, that patient's drafts |
| `/console/usage` | LLM usage per day, per patient and per model from the `llm_usage` audit rows: calls, tokens and estimated USD (`?days=7|30|365`) |

Console actions go through the same `Orchestrator.handle_doctor_command` path as the WhatsApp commands, so every
approval is logged and the doctor's control number still gets the confirmation. Cost estimates use the price table in
`app/pricing.py` (Anthropic list prices, Oct 2026, including cache reads/writes); rows written before per-model
accounting are priced as `AGENT_MODEL` and marked with `*`. WhatsApp conversation fees are not included.
Put the console behind HTTPS (the cookie is marked `secure` only when served over HTTPS) and never share the token.

## Appointment reminders (`python -m app.reminders`)

Sends a WhatsApp **template** message the day before each booking in `data/calendar.json`:

```bash
.venv/bin/python -m app.reminders --dry-run          # print the plan, send nothing, write nothing
.venv/bin/python -m app.reminders --date 2026-10-25  # a specific day (default: tomorrow)
.venv/bin/python -m app.reminders                    # live only when DRY_RUN=false; run it from cron once a day
```

Rules enforced in code: a reminder goes only to patients whose record has `consent_at` set and `opted_out = 0`
(one message per patient, listing all their slots); every real send is logged to `messages` (action `REMINDER`) and
`audit_log` (`reminder_sent` / `reminder_failed`). Patients who never messaged the clinic have no record and are skipped.

Business-initiated messages are outside WhatsApp's 24-hour service window, so Meta requires **(a)** an approved
message template and **(b)** the patient's opt-in. Before going live:

1. In Meta Business Manager > WhatsApp Manager > Message templates, create a *Utility* template named as
   `REMINDER_TEMPLATE_NAME` (default `appointment_reminder`) in language `REMINDER_TEMPLATE_LANGUAGE` with exactly four
   body placeholders, e.g. `Hello {{1}}, this is a reminder of your appointment with {{2}} on {{3}} at {{4}}. Reply to this
   message if you need to reschedule.` Placeholders are filled as: patient name, `Dr. <DOCTOR_NAME>`, date and time(s),
   `CLINIC_NAME`. Wait for Meta's approval (usually minutes to a day).
2. Opt-in: the consent notice on first contact covers appointment messages; keep the notice text and the STOP keyword as
   they are (opt-outs are honoured automatically). Utility templates are billed per message (₹0.115 in India from Oct 2026).

`WhatsAppClient.send_template(to, template_name, language, components)` is the only outbound path for templates.

## Postgres

SQLite is the default and needs nothing. For production set

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/sevadesk
```

`psycopg[binary]` (psycopg 3) is in `requirements.txt`; bare `postgresql://` URLs are rewritten to the psycopg driver,
and the pool uses `pool_pre_ping`. Tables are created on start-up (`Base.metadata.create_all`); add Alembic before the
schema needs a migration. The `timezone=True` datetime columns store UTC in both engines.

## Run it locally (no WhatsApp needed)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env             # fill ANTHROPIC_API_KEY (or run `ant auth login`); keep DRY_RUN=true; set CONSOLE_TOKEN
                                 # ANTHROPIC_WORKSPACE_ID is needed only for an org-level key
.venv/bin/python seed_calendar.py   # generate upcoming slots
.venv/bin/python -m pytest -q   # 65 tests, no network, no API key needed (scripted FakeLLM)
.venv/bin/python simulate.py    # chat as a patient; add --doctor to act as the doctor
.venv/bin/uvicorn app.main:app --reload --port 8000   # then POST /simulate {"from_wa_id":"9199...","text":"..."}
                                                      # and open http://localhost:8000/console
```

In dry-run mode every outbound WhatsApp message is printed instead of sent, and the console, `/simulate` and
`python -m app.reminders --dry-run` all work without an API key (the emergency gate and doctor commands never call the model).

## Go live (pilot doctor)

1. Meta for Developers: create an app, add WhatsApp, verify the business.
2. Onboard the doctor's number with **Coexistence** (WhatsApp Business app stays usable; app replies arrive as `message_echoes`).
   Subscribe the webhook to `messages` and `message_echoes`.
3. Expose `POST /webhook` over HTTPS (ngrok for the pilot), set `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`,
   `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `DOCTOR_CONTROL_NUMBER`, the clinic identity fields, and `DRY_RUN=false`.
   The webhook verifies `X-Hub-Signature-256` whenever `WHATSAPP_APP_SECRET` is set, rejects (403) payloads whose
   `metadata.phone_number_id` differs from `WHATSAPP_PHONE_NUMBER_ID` (when set), and logs-and-ignores delivery/read
   status updates.
4. Edit `data/clinic_kb.json` (doctor-written FAQs) and `data/reports.json`; run `.venv/bin/python seed_calendar.py` to generate a week of slots (re-run weekly, or replace with your PMS).
5. Optional: `SARVAM_API_KEY` for Hindi/regional voice-note transcription.

## Models and cost

`AGENT_MODEL` defaults to `claude-opus-5-5` at `AGENT_EFFORT=low`; switch to `claude-sonnet-5-5` or `claude-haiku-5-5`
for routine traffic once the pilot shows draft-acceptance is stable (see unit economics in the research report).
The system prompt is cached (`cache_control`), the final answer is schema-constrained JSON, and tools are `strict`.
Every LLM call's token usage (and the model used) is written to the `audit_log` table (event `llm_usage`); `/console/usage` turns it into per-day, per-patient and per-model cost.
`ENABLE_FALLBACKS=true` turns on Anthropic's server-side refusal fallback (beta); it is off by default because the
orchestrator already converts any refusal into a draft for the doctor.

## What is deliberately NOT here yet

- Redis / task queue (FastAPI background tasks are enough for one clinic; Postgres is supported, see above)
- Clinic PMS / Google Calendar integration (JSON slot store for now)
- Schema migrations (Alembic) and multi-doctor tenancy
- Fine-tuned classifier; the regex gate + Claude classification are the MVP
- Console users/roles: one shared `CONSOLE_TOKEN` per deployment
