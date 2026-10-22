# SevaDesk pilot runbook: first doctor, from zero to live

Written 22 Oct 2026 for the first pilot doctor in India. Facts about Meta's platform come from
`research_notes/whatsapp_platform_rules_pricing_regulation.md` (sourced, dated); verify anything marked **check**
against Meta's current pages on the day you do it, because Meta changes onboarding flows often.

Expected effort: about 2 working days of your time spread over 1-2 weeks (Meta business verification is the long pole),
plus 30 minutes of the doctor's time on their phone.

---

## 0. Choose the pilot doctor and agree the ground rules

Pick a doctor who:
- Already uses the **WhatsApp Business app** (not personal WhatsApp Messenger) on the clinic number, or is willing to
  migrate (Messenger → Business app keeps chats on the phone). An account that was created very recently may not be
  eligible for Coexistence yet; Meta ties eligibility to account tenure and messaging quality. Prefer a number that has
  been on the Business app for months.
- Gets 50+ patient messages a day (paediatrics, dermatology, gynaecology, general practice are best).
- Has a **second phone number** (their personal number or a receptionist's) to receive drafts and emergency pages.
  This becomes `DOCTOR_CONTROL_NUMBER`.
- Will spend 10 minutes a day for the first two weeks reviewing drafts and rejected replies with you.

Agree in writing (one page, signed):
1. The assistant answers only administrative and reassurance messages on its own; every clinical question is a draft
   the doctor sends in their own words (Telemedicine Practice Guidelines 2020, cl. 5.4). The doctor remains the RMP of record.
2. The doctor's NMC registration number appears in the assistant's identity line (already in the prompt).
3. Patients are told they are talking to an AI on first contact (consent notice) and can opt out with STOP.
4. Data: messages are stored on the clinic's server (or yours, as processor), in India, retained for the period you
   agree (suggest 1 year, then delete), breach notification to the doctor within 24 hours (DPDP requires the Data
   Fiduciary to notify the Board within 72 hours).
5. You, not the doctor, own Meta platform fees and the hosting bill during the pilot.
6. Either side can stop the pilot any day by switching the mode to `off`.

---

## 1. Meta app setup checklist (your side, before touching the doctor's phone)

Do this with your own Facebook login and a business you control (you are the "tech provider"; the doctor's number
is onboarded into a WhatsApp Business Account you manage, or into the doctor's own, see 1.5).

- [ ] **1.1 Meta Business Portfolio.** business.facebook.com → create a portfolio for your company (legal name, address,
      website or a public page). Keep the portfolio ID handy.
- [ ] **1.2 Business verification.** Business settings → Security centre → Start verification. Upload GST registration or
      incorporation certificate plus a utility bill or bank statement with the same address. Takes hours to two weeks.
      You can build and test before this completes, but messaging limits stay at 250 unique users per day until it is done.
- [ ] **1.3 Developer app.** developers.facebook.com → Create app → type "Business" → add the **WhatsApp** product.
      Note the **App ID** and **App Secret** (`WHATSAPP_APP_SECRET`).
- [ ] **1.4 Test number first.** The app comes with a free Meta test number and a temporary token. Use it to verify the
      webhook end to end (step 3) before involving the doctor's real number.
- [ ] **1.5 WhatsApp Business Account (WABA).** Decide ownership:
      - *Recommended for the pilot:* the WABA lives in **your** portfolio and the doctor's number is added to it.
        Fast, you control billing.
      - *Long-term:* each clinic has its own portfolio and WABA; you are added as a partner. Switch to this before
        you scale, because Coexistence numbers cannot be moved between WABAs later.
- [ ] **1.6 Payment method.** WhatsApp Manager → Payment settings → add a card. Without it Meta stops delivering replies
      after the 1,000 free service messages per number per month (India rate after that: ₹0.115 per reply, rate card
      effective 1 Oct 2026). INR billing becomes mandatory for Indian businesses by 31 Dec 2026 **check**.
- [ ] **1.7 System user and permanent token.** Business settings → Users → System users → Add (Admin) → Assign assets
      (your app + the WABA) → Generate token with `whatsapp_business_messaging` and `whatsapp_business_management`.
      This is `WHATSAPP_TOKEN`. Never use the 24-hour temporary token in production.
- [ ] **1.8 Webhook subscription.** App dashboard → WhatsApp → Configuration → Callback URL = `https://<your-host>/webhook`,
      Verify token = the value you put in `WHATSAPP_VERIFY_TOKEN`. Subscribe to **`messages`** and **`message_echoes`**
      (echoes are how the agent sees what the doctor typed from the phone app). Do not subscribe to things you do not handle.
- [ ] **1.9 Display name.** Set the WABA phone display name to the clinic name exactly as on signage (Meta reviews it).
- [ ] **1.10 Reminder template (optional for week 1).** WhatsApp Manager → Message templates → Create → Category
      *Utility*, name `appointment_reminder`, language `en` (and `hi`), body with exactly four placeholders:
      `Hello {{1}}, this is a reminder of your appointment with {{2}} on {{3}} at {{4}}. Reply here to reschedule.`
      Approval takes minutes to a day. Needed only for `python -m app.reminders`.

---

## 2. Coexistence onboarding (the doctor's phone, 30 minutes, you sit next to them)

Coexistence lets the doctor keep using the WhatsApp Business app on the same number while the Cloud API also
receives and sends messages. What the doctor must know before saying yes:

| Keeps working | Changes |
|---|---|
| The Business app on the phone, chat history on the phone | Companion apps (WhatsApp Web, Windows, WearOS) are unlinked and not supported |
| Replying by hand from the phone, any time | Must open the Business app at least once every **13 days** or the account disconnects |
| Up to **6 months** of 1:1 chat history can be synced to the API at onboarding | Group chats never sync and the agent cannot see them |
| Messages sent from the app stay free | Replies sent by the agent are billed by Meta after the free tier |
| | Disappearing messages and view-once stop working |
| | No blue badge (Official Business Account) for this number |

Steps:
- [ ] **2.1 Pre-flight on the phone.** WhatsApp Business app updated to **2.24.17 or later** (Play Store). Phone backed
      up (Settings → Chats → Chat backup). Confirm the number is NOT already registered on the Cloud API.
- [ ] **2.2 Start Embedded Signup from your tech-provider app** (Meta's Coexistence onboarding runs through Embedded
      Signup; BSPs such as 360dialog, Interakt or Gupshup expose the same flow with a button labelled "Connect existing
      WhatsApp Business app number" **check the current label**). Choose "I already use the WhatsApp Business app".
- [ ] **2.3 Scan the QR / approve on the phone.** The app shows a "Business Platform" connection prompt; the doctor
      approves it. Choose **sync 6 months of history** (it gives the agent context for ongoing patients; skip if the
      doctor objects on privacy grounds, the agent still works for new messages).
- [ ] **2.4 Verify in WhatsApp Manager** that the number shows as connected with the Business app, and note the
      **Phone number ID** (`WHATSAPP_PHONE_NUMBER_ID`). Status should be "Connected"; quality rating starts green.
- [ ] **2.5 Save the doctor's control number** (`DOCTOR_CONTROL_NUMBER`, digits only with country code, e.g. `9198xxxxxxxx`).
      Send it a test message from the clinic number so the 24-hour window is open in both directions.
- [ ] **2.6 Set a calendar reminder** for the doctor (every 10 days) to open the Business app, until the habit is proven.

Disconnecting later (rollback): on the phone, Settings → Account → Business Platform → Disconnect. The app keeps working.

---

## 3. Server deployment

Minimum for one clinic: a single small VM or PaaS instance in India with HTTPS.

- [ ] **3.1 Host.** AWS Mumbai (`ap-south-1`) t4g.small, or Railway/Render with the region set to Singapore if India is
      unavailable **check**; data residency matters for DPDP and for the clinic contract. Postgres: RDS Mumbai or the
      PaaS add-on. For week 1 SQLite on the VM is acceptable; switch to Postgres before a second doctor.
- [ ] **3.2 Clone and install.**
      ```bash
      git clone https://github.com/devashishb-rms/healthcare-agents-and-assistants.git
      cd healthcare-agents-and-assistants/doctor-whatsapp-agent
      python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
      cp .env.example .env
      ```
- [ ] **3.3 Fill `.env`** (every line matters):
      - `ANTHROPIC_API_KEY` (and `ANTHROPIC_WORKSPACE_ID` if the key is org-level). Put the key in a workspace with a
        spend limit (~$30/month covers a busy solo clinic many times over).
      - `AGENT_MODEL=claude-sonnet-5-5`, `AGENT_EFFORT=low` for the pilot (verified live, ~$0.005 per reply).
      - `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`.
      - `DOCTOR_CONTROL_NUMBER`, `DOCTOR_NAME`, `DOCTOR_QUALIFICATIONS`, `SPECIALITY`, `NMC_REG_NO`, `CLINIC_NAME`,
        `CITY`, `CLINIC_PHONE`, `ASSISTANT_NAME`, `REGIONAL_LANGUAGES`.
      - `DEFAULT_MODE=draft` for go-live day (see section 5), `BACKOFF_MINUTES=10`.
      - `CONSOLE_TOKEN` = 32+ random characters (`openssl rand -hex 24`).
      - `DATABASE_URL`, and `SARVAM_API_KEY` if the clinic gets many Hindi/regional voice notes.
      - Keep `DRY_RUN=true` until step 4.4.
- [ ] **3.4 Clinic content.** With the doctor, fill `data/clinic_kb.json` (timings, fees, address, what to bring, test
      preparation, the 5-10 questions they answer twenty times a day, and any "expected after-procedure" notes written
      in the doctor's own words). Run `python seed_calendar.py` (or wire your PMS) and fill `data/reports.json` or
      point the report tool at the lab's system.
- [ ] **3.5 Run it.** `uvicorn app.main:app --host 0.0.0.0 --port 8000` behind nginx/Caddy with TLS, or the PaaS's
      HTTPS. Run it as a service (systemd) so it restarts. Set `TZ=Asia/Kolkata`.
- [ ] **3.6 Reminders cron (optional).** `0 18 * * * cd .../doctor-whatsapp-agent && .venv/bin/python -m app.reminders`
      sends next-day reminders at 6 pm to consenting patients only.
- [ ] **3.7 Backups.** Nightly dump of the database and `data/` to an encrypted bucket in Mumbai; 30-day retention.

---

## 4. Verification before any patient sees it

- [ ] **4.1 Offline.** `DRY_RUN=true .venv/bin/python -m pytest -q` → 65 passed.
- [ ] **4.2 Webhook handshake.** In the Meta app dashboard click "Verify and save"; the server log shows the GET and
      Meta shows a green tick. Then "Test" a `messages` event; the log shows the payload parsed and (in dry run) the
      reply printed, not sent.
- [ ] **4.3 Simulated conversation.** `.venv/bin/python simulate.py` and walk through: timings question (ADMIN, sent),
      booking (uses real slots), a medicine question (CLINICAL, holding message + draft to the control number),
      "seene me dard" (EMERGENCY script within a second, no LLM), `status` and `E<id> ...` from `--doctor`.
- [ ] **4.4 Real number, your phone only.** Set `DRY_RUN=false`, restart, message the clinic number from your own
      phone: consent notice arrives, then the answer. Check the console at `/console` shows the conversation and the
      usage page shows tokens. Send `status` from the control number; the reply must arrive on the doctor's second phone.
- [ ] **4.5 Echo check.** Have the doctor reply to your test chat from the Business app; the server log shows a
      `message_echoes` event and your next message gets `silent_backoff` for 10 minutes.
- [ ] **4.6 Emergency drill.** From your phone send "mujhe saans nahi aa rahi". Confirm the scripted 108/112 reply
      and the page on the control number. Then send "I don't want to live anymore" and confirm the Tele-MANAS 14416 line
      is included. Both must happen with no LLM call in the log.

---

## 5. Go-live sequence (two weeks)

| Day | Mode | What happens | Exit criterion |
|---|---|---|---|
| 0 | `off` | Live webhook, agent only logs and classifies. Review the console at end of day: do the classifications look right on the doctor's real traffic? | 95%+ of a 50-message sample classified sensibly; zero missed emergencies in the sample |
| 1-3 | `draft` | Patients get the consent notice and an acknowledgement; **every** reply waits for the doctor's A/E/X. Doctor approves from the phone. | Doctor accepts ≥70% of admin drafts unchanged |
| 4-10 | `auto` | Admin and social replies go out immediately; clinical stays draft. You review the console daily and read every rejected or edited draft. Fix the KB, not the prompt, first. | p50 first response < 60 s; complaints 0; doctor reports time saved |
| 11-14 | `auto` | Turn on reminders if the template is approved. Collect the pilot numbers below. | Decide: continue, expand to a second doctor, or stop |

The doctor controls the mode from their phone at any time: send `auto`, `draft` or `off` to the clinic number from the
control number, or use the console.

**Pilot metrics to record (the console usage page plus a weekly export):** messages/day, % handled autonomously,
drafts created / approved / edited / discarded, p50 and p95 first-response time, emergency pages (and whether each was a
true emergency), opt-outs, patient complaints, LLM cost, Meta message cost, doctor's self-reported minutes saved per day.

---

## 6. Daily and weekly operations

Daily (5 minutes, you): open `/console`, clear anything pending more than 2 hours (call the doctor), read emergency
pages from the last 24 hours, skim 10 random conversations for tone and correctness, check the quality rating in
WhatsApp Manager is still green.

Weekly: re-run `seed_calendar.py` (or confirm PMS sync), update the KB from the week's edited drafts, export metrics,
check Meta billing and Anthropic spend, rotate the console token if anyone left the team, confirm the doctor opened the
Business app in the last 13 days.

---

## 7. Incident playbook

| Incident | Immediate action | Follow-up |
|---|---|---|
| Agent sent something clinical or wrong | Doctor sends `off` from the control number (or you set it in the console); doctor messages the patient personally from the app | Pull the conversation from the console; add a regex to `app/safety.py` or a rule to the prompt; add a test; re-run the suite; resume in `draft` mode |
| Emergency not detected by the gate (patient later turned out to be an emergency) | Call the patient and the doctor now | Add the exact phrasing to `EMERGENCY_PATTERNS` with a test the same day; report in the weekly review |
| Patient complains about talking to a bot | Reply personally, offer opt-out | Check the consent notice wording with the doctor; consider `draft` mode for that patient's thread |
| WhatsApp quality rating turns yellow/red | Stop all template sends (`reminders` cron off) | Find the blocked/reported conversations in the console; usually unwanted reminders |
| Number disconnected (13-day rule or app uninstalled) | Doctor opens the Business app; re-run Coexistence onboarding if needed | Set the 10-day reminder again |
| Webhook down (Meta retries for up to 7 days; duplicates are ignored by id) | Restart the service; replies will catch up; patients who waited get an apology template if >24 h | Add uptime monitoring (a free pinger on `/health`) |
| Anthropic API error or spend limit hit | The agent falls back to "doctor will reply personally" drafts automatically | Raise the workspace limit; check `/console/usage` |
| Suspected data breach | Switch mode `off`, rotate `WHATSAPP_TOKEN`, `CONSOLE_TOKEN`, API key; preserve logs | Notify the doctor within 24 h; the doctor (Data Fiduciary) notifies the DPDP Board within 72 h; written incident report |

---

## 8. Compliance checklist for the pilot file

- [ ] Signed pilot agreement (section 0) naming the doctor as RMP and Data Fiduciary, you as Data Processor.
- [ ] Consent notice text (in `.env`) reviewed by the doctor; patient-initiated chats count as implied consent under TPG
      2020 §3.4.1; reminders require recorded opt-in (consent_at is set only after the patient continues past the notice).
- [ ] Privacy notice (one page in English and Hindi) available on request and linked from the clinic's board.
- [ ] Data stored in India; retention period and deletion process written down; backups encrypted.
- [ ] The assistant never counsels or prescribes (CLINICAL is always a draft; verified by tests `test_llm_cannot_send_clinical_even_if_it_says_send`).
- [ ] Doctor's registration number shown in the assistant's identity (prompt).
- [ ] No health claims in any marketing (Drugs and Magic Remedies Act); the product is a front desk, not a diagnostic tool.
- [ ] Meta Business Messaging Policy: the bot serves this clinic's own patients only (ancillary use, allowed); no use of
      platform data to train shared models.

---

## 9. Costs to expect for one solo clinic in the pilot (per month)

| Item | Amount |
|---|---|
| Meta service messages | ₹0 for the first 1,000 replies, then ₹0.115 each (3,000 replies ≈ ₹230) + GST |
| Reminder templates (utility) | ₹0.115 each |
| Anthropic (Sonnet 5.5, low effort, ~5k cached input + 150 output per turn) | roughly ₹400-1,000 for 3,000 replies; the Max plan's monthly API credit covers this |
| Hosting (small VM Mumbai or PaaS) | ₹1,500-4,500 |
| Sarvam STT (optional, voice notes) | ₹0.50 per minute of audio |

At ₹2,499/month per doctor the pilot clinic is roughly break-even on direct costs; margin comes from the second
doctor on the same server.
