# Saathi – AI mental-wellbeing companion (Product 2), Phase 1: safety core

Saathi is a **wellness companion**, not a therapist, psychologist, psychiatrist, doctor or counsellor. It never
diagnoses, never treats, never advises on medicines, and never gives method or lethality information under any framing.
It is for **adults (18+) only**. Anyone at risk is routed to humans: Tele-MANAS 14416 / 1-800-891-4416, 112 / 108,
Vandrevala +91 9999 666 555, iCall 9152987821, AASRA +91-22-27546669, 181 (women), 1098 (children), 988 (US),
Samaritans 116 123 (UK). Those are the only numbers the product can ever say.

Phase 1 (plan section 2.4) is the safety core that must be green **before any user sees the bot**: pre-turn risk gate,
deterministic router, scripted crisis flow with LLM-worded warmth, helpline directory, post-turn output guard, and an
eval harness on a red-team vignette set. The design and the three prompts are in
`../docs/Healthcare AI agents build plan and prompts.md`, section 2.

## Run

```bash
cd ai-counsellor
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../doctor-whatsapp-agent/.env .env        # ANTHROPIC_API_KEY (+ ANTHROPIC_WORKSPACE_ID); never commit it
.venv/bin/python -m pytest -q                # 214 tests, no network, FakeLLM + stub client
.venv/bin/python evals/run_evals.py          # gate + full pipeline with the FakeLLM
.venv/bin/python evals/run_evals.py --live   # real models: claude-sonnet-5-5 companion, claude-haiku-5-5 classifier + guard
.venv/bin/python chat.py                     # REPL against the real models (--fake for rules + scripts only)
```

Settings come from `.env` / environment via `app/config.py` (models, effort, whether the LLM classifier, LLM guard and
LLM crisis wording are on, session nudge minutes, SQLite URL).

## How a message flows (`app/companion.py`)

1. **Commands**: `HUMAN` queues a human handoff; `delete my data` erases everything (DPDP). `mood 6/10` logs mood.
2. **Risk gate** (`app/risk.py`) runs on *every* message, including during onboarding.
   Rules first: regexes for English, Hinglish and Devanagari across passive / active ideation, plan, means, intent,
   timeframe, in-progress, NSSI, harm to others, abuse, psychosis markers, purging, overdose, medical emergency, minor
   indicators and method requests (including fiction / research / hypothetical / "for a friend" framings).
   Then the claude-haiku-5-5 classifier with the plan's prompt. **The classifier can only raise the level, never lower
   it.** If it refuses, truncates or returns malformed JSON, the turn is treated as IMMINENT ("when unsure, escalate");
   only an API error (the model never saw the text) leaves the rules alone in charge. The emergency step (112/108) is
   opened only on ingestion / in-progress / medical signals the *rules* found, never on a classifier tag alone.
   Combination rules: any in-progress / overdose / medical / method-request → IMMINENT; ideation + plan/means/intent →
   IMMINENT; active ideation + timeframe → IMMINENT; means + timeframe → IMMINENT; otherwise any flagged category →
   ELEVATED. When unsure, escalate.
3. **Age gate + consent** on first contact (18+, storage consent). Under-18 signals at any point → the minor script
   (Childline 1098, Tele-MANAS 14416, 112, "tell one adult you trust") and the companion never engages. A crisis
   message during onboarding is answered as a crisis, not with an age question.
4. **Router**: IMMINENT, or an active crisis flow → `CrisisFlow`; ELEVATED → the elevated track of `CrisisFlow`
   (or, if that track already completed this session, the companion with an elevated instruction); NONE → companion.
5. **Crisis flow** (`app/crisis.py`) is a fixed state machine. IMMINENT: presence + the two safety questions (with
   Tele-MANAS in the footer) → emergency step (112/108, verbatim, never reworded) if they have acted → helpline +
   second line + in-app handoff → means safety (never names the method) → reasons for living → check-in loop until
   human contact is confirmed. `handoff_requested` is true from the first IMMINENT turn and every flagged turn lands in
   the clinician review queue table. ELEVATED: acknowledge → "thoughts of ending your life?" → "any plan?" (yes →
   IMMINENT track) → six-item safety plan, one item per turn, saved to the user's profile → offer Tele-MANAS and a
   professional → back to the companion with a follow-up instruction next session. Special scripts: abuse (181 / 1098
   / 112), harm to others, psychosis (never validate, never argue), purging, medical emergency.
   The LLM may **reword** a scripted message (`CRISIS_WORDING_PROMPT`); the reworded text must pass the guard and keep
   every required number, else the script is sent as-is.
6. **Companion** (claude-sonnet-5-5, system prompt from plan 2.5, memory variables filled from SQLite, strict JSON
   output). If the model itself reports IMMINENT, the turn is re-routed into the crisis flow.
7. **Output guard** (`app/guard.py`): regex hard checks (diagnosis labels, medicine names / dosing, method / lethality /
   quantity / location info, "committed suicide", numbers not in the directory, more than 6 lines, claims of being
   human or a clinician, romantic / exclusive framing, agreeing with self-condemnation or delusions, more than one
   exercise, any exercise or tip while risk is imminent, ending / refusing while at risk) followed by a
   claude-haiku-5-5 check with the plan's guard prompt. Fail → regenerate once with the fix instruction → fail again →
   scripted safe fallback. A guard verdict that is truncated, malformed or refused counts as a fail.
8. **Memory** (`app/memory.py`, SQLite): what_helps / supports / triggers, safety plan, mood log, messages, crisis
   state, review queue. **Session nudge** after ~60 minutes in one session (never during a crisis).

## Evals (`evals/`)

`vignettes.jsonl` has 79 Indian-context vignettes (exam failure, family pressure, debt, farmer distress, breakup,
domestic abuse, postpartum, LGBTQ+ rejection, elderly isolation, psychosis markers, method requests framed as fiction /
research / hypothetical / "for a friend", passive ideation in Hinglish and Devanagari, minors, medication and diagnosis
bait, long-conversation degradation, and 27 benign controls that must **not** trigger crisis). Each has an expected
level, `must_any` / `must_not` substrings for the final reply, and optionally an expected mode.

`run_evals.py` scores (a) the regex gate alone and (b) the full pipeline, with the FakeLLM by default and real models
with `--live`. It prints IMMINENT recall, ELEVATED recall (≥ ELEVATED), false-positive rate on benign cases, reply
checks, regenerations and fallbacks.

### Results

Regex gate alone and FakeLLM pipeline (deterministic, 2026-10-22): IMMINENT recall 25/25, ELEVATED recall 27/27,
false positives 0/27, reply checks 79/79 (the FakeLLM run skips `must_any` on the five vignettes marked `needs_llm`). **Caveat:** the regexes were tuned against this very set, so these numbers
measure coverage of known phrasings, not generalisation. Phase 0's 150-300 clinician-written vignettes and a held-out
split are what will make the recall number mean something.

Live run (claude-sonnet-5-5 companion, claude-haiku-5-5 classifier and guard), 2026-10-22:

| Metric (full pipeline, 79 vignettes) | Result |
|---|---|
| IMMINENT recall (level + `handoff_requested`) | 25/25 |
| ELEVATED recall (≥ ELEVATED) | 27/27 on level; 26/27 on reply checks |
| False-positive rate on 27 benign cases | 7/27 (25.9%) |
| Reply must/must-not checks | 71/79 |
| Companion-model fallbacks to scripted text | 0 |
| Crisis rewordings rejected by the guard → script sent verbatim | 24 |
| Truncated / malformed / refused model outputs | 0 |

Reading the numbers:

- **Every imminent case was caught, routed to the crisis flow, and set `handoff_requested`**, including the method
  requests framed as fiction, research, "hypothetically" and "for a friend", the 23-turn benign-then-imminent chat and
  the 15-turn slow escalation ending in a fiction-framed dose question.
- **All 7 false positives are the Haiku classifier**, not the rules: it labelled realistic benign Indian-context
  sadness (a 2-mark JEE miss, daily taunts at home, a two-week-old breakup, postpartum tiredness, "aaj bahut akela
  feel ho raha hai") as ELEVATED, so those users were met with the scripted "have you been having thoughts of ending
  your life?" on turn one. That is the plan's own rule ("when unsure between NONE and ELEVATED choose ELEVATED") doing
  exactly what it says; the cost is a safety question, the benefit is recall. Whether 1 in 4 sad users should get that
  question on their first message is a clinical-lead decision for Phase 2. Two mitigations are ready to try: route a
  *classifier-only* ELEVATED (rules NONE, low confidence) to the companion with an elevated instruction rather than the
  scripted questions; or let the ELEVATED track "explore the pain for a few turns" (plan 2.5) before asking.
- **The guard is strict with the model's crisis wording.** In 24 of the crisis turns the Haiku guard rejected the
  Sonnet rewording (typical reasons: "implies feelings of care", "no helpline on this turn", "says I'm staying here")
  and the scripted text was sent instead. Nothing unsafe reached the user; the user just got plainer text. The guard
  does not currently see the approved script it is judging against, so it re-litigates structure decisions the
  orchestrator already made. Giving it the script as context is the obvious next tweak.
- The one ELEVATED reply-check miss is a companion-model reply to a renewed "feel like disappearing" late in a
  session that reflected well but did not repeat the Tele-MANAS number as instructed.
- Two live bugs were found and fixed by this run before the final numbers: Haiku output truncated at the old
  `max_tokens=400` (now 1024, with the quote bounded in the prompt, and any truncated / malformed / refused classifier
  output escalating to IMMINENT while a malformed guard verdict fails the draft), and a classifier-only
  "overdose_substance" or "medical_emergency" tag opening the ambulance script on a fiction dose question or a
  sleepless psychosis disclosure (now only the regex layer, which is precise about actual ingestion, can open it).
- Three live runs cost roughly 15 minutes each at about 11 seconds per vignette; full outputs are in
  `evals/live_results.json` (git-ignored) and the run log.

## What Phase 2 adds

Companion core (plan 2.4): the clinician-written content library (breathing, grounding, behavioural activation, sleep,
sunlight, hydration, thinking tools; spiritual practices only when user-held) delivered one at a time; validated
screeners (PHQ-9, GAD-7, ASQ, AQ-10) with signposting copy and the PHQ-9 item-9 → crisis rule; Hindi + English + two
regional languages; richer memory and session summaries; proactive follow-up after flagged sessions; WhatsApp ingress
reused from `../doctor-whatsapp-agent/`. Phase 3 adds the clinician review console on top of the `review_queue` table,
warm handoff to partner counsellors and the incident process.

## What is deliberately NOT here

- No diagnosis, no screeners yet, no medicine advice, no method or lethality information under any framing.
- No fine-tuned classifier: the LLM classifier is prompted (claude-haiku-5-5) and sits *on top of* the rules; the
  labelled vignette data is the start of a fine-tuning set, not the end.
- No human review console, no real handoff transport: `handoff_requested` and the `review_queue` table are the hooks.
  Nobody should use this with real users until a clinician reviews flagged sessions within an SLA.
- No children: under-18 signals end the conversation with Childline 1098. No parental-consent flow.
- No WhatsApp / web channel, no auth, no rate limits, no encryption at rest, no India-region hosting: the orchestrator
  is a library with a REPL. Those are gateway concerns to be reused from SevaDesk.
- No invented helplines: the directory in `app/crisis.py` is the whole list, and the guard rejects any other number.
- No clinical sign-off: the crisis script wording, the safety-plan structure and the vignette labels were written by an
  engineer from the plan and the research notes, not by the clinical lead Phase 0 requires. Treat them as drafts.
