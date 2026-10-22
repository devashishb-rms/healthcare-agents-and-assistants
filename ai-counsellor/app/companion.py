"""Orchestrator: age gate + consent -> risk gate -> router -> (crisis flow | companion LLM) -> guard -> reply.

Everything the LLM produces passes through `OutputGuard`; everything it is asked to do is bounded by the risk gate and
the crisis state machine. The LLM is never the thing that decides whether someone is in crisis: it can only raise the
level the rules found (via its own `risk_observed`), never lower it.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from .config import Settings
from .crisis import (ACKNOWLEDGE, HUMAN_CONFIRMED, PRIMARY_HELPLINE_NAME, PRIMARY_HELPLINE_NUMBER, SUPPORT, CrisisFlow,
                     CrisisState, CrisisTurn, directory_text)
from .guard import OutputGuard
from .memory import Message, MoodLog, ReviewItem, User, delete_user_data, get_or_create_user, mood_summary, recent_messages, utcnow
from .prompts import (AGE_CONSENT_MESSAGE, COMPANION_OUTPUT_SCHEMA, CRISIS_WORDING_PROMPT, CRISIS_WORDING_SCHEMA,
                      OPENING_MESSAGE, SYSTEM_PROMPT, render)
from .risk import ELEVATED, IMMINENT, NONE, RiskAssessment, RiskGate, max_level

log = logging.getLogger("saathi.companion")


# --------------------------------------------------------------------------------------------
# LLM interface
# --------------------------------------------------------------------------------------------
class CompanionOutput(BaseModel):
    risk_observed: str = NONE
    flags: list[str] = Field(default_factory=list)
    mode_suggestion: str = "companion"
    reply: str = ""
    memory_updates: dict = Field(default_factory=lambda: {"what_helps": [], "supports": [], "triggers": []})
    handoff_requested: bool = False


class CompanionLLM(Protocol):
    def respond(self, system: str, messages: list[dict]) -> CompanionOutput | None: ...
    def word_crisis(self, script: str, instruction: str, messages: list[dict]) -> str | None: ...


class ClaudeCompanionLLM:
    def __init__(self, client, model: str = "claude-sonnet-5-5", effort: str = "low"):
        self.client, self.model, self.effort = client, model, effort

    def respond(self, system: str, messages: list[dict]) -> CompanionOutput | None:
        from .llm import structured_call

        data = structured_call(self.client, model=self.model, system=system, messages=messages,
                               schema=COMPANION_OUTPUT_SCHEMA, effort=self.effort, max_tokens=1024)
        if not data:
            return None
        try:
            return CompanionOutput.model_validate(data)
        except ValidationError as e:
            log.error("bad companion JSON: %s", e)
            return None

    def word_crisis(self, script: str, instruction: str, messages: list[dict]) -> str | None:
        from .llm import structured_call

        system = render(CRISIS_WORDING_PROMPT, script=script, instruction=instruction)
        data = structured_call(self.client, model=self.model, system=system, messages=messages or [{"role": "user", "content": "(start)"}],
                               schema=CRISIS_WORDING_SCHEMA, effort=self.effort, max_tokens=400)
        return (data or {}).get("reply") or None


# --------------------------------------------------------------------------------------------
# Reply
# --------------------------------------------------------------------------------------------
@dataclass
class Reply:
    text: str
    mode: str                               # onboarding | minor | companion | crisis | safety_plan | handoff | wind_down | fallback
    risk_level: str = NONE
    categories: list[str] = field(default_factory=list)
    handoff_requested: bool = False
    flags: list[str] = field(default_factory=list)
    guard_violations: list[str] = field(default_factory=list)
    crisis_stage: str = ""
    llm_used: bool = False
    regenerated: bool = False
    fallback_used: bool = False


# --------------------------------------------------------------------------------------------
# Small parsers
# --------------------------------------------------------------------------------------------
_YES = re.compile(r"^\W*(yes|yeah|yep|yup|y|ya|haan|ha|han|hn|ji|ji haan|haa|हाँ|हां|जी|ok|okay|sure|agree|i agree|confirm|continue|theek hai|thik hai|18\+|i am 18|i'm 18|im 18|over 18|above 18|adult)\b", re.I)
_NO = re.compile(r"^\W*(no|nope|nah|nahi|nhi|na|नहीं|not yet|under 18|below 18|minor|i'?m not 18|not an adult)\b", re.I)
_AGE = re.compile(r"(?<!\d)(\d{2})(?!\d)")
_MOOD = re.compile(r"^\s*(?:/?mood|mood is|mood:|my mood|mera mood|feeling)\s*[:=]?\s*(\d{1,2})(?:\s*/\s*10)?\b|\b(\d{1,2})\s*/\s*10\b", re.I)
_HUMAN_CMD = re.compile(r"^\s*(human|HUMAN|insaan|person|talk to a (human|person)|real person)\s*[.!]*\s*$", re.I)
_DELETE_CMD = re.compile(r"^\s*(delete|delete my data|forget me|erase my data|delete everything)\s*[.!]*\s*$", re.I)
_ASKS_IF_HUMAN = re.compile(r"\b(are you (a )?(human|real|bot|ai|robot|person)|am i talking to a (human|bot|person|machine)|kya aap (insaan|robot|ai|machine) ho|kya tum (insaan|robot|ai) ho|is this a (bot|real person)|tum (insaan|robot|ai) ho)\b", re.I)

FALLBACK_COMPANION = ("I'm here with you. I want to be careful with my words, so I'll keep it simple: what you're going through sounds hard, "
                      "and you don't have to carry it alone.\nWhat's weighing on you most right now?")
FALLBACK_ELEVATED = ("I'm here with you, and I'm glad you're talking. Things sound very heavy right now.\n"
                     f"{PRIMARY_HELPLINE_NAME} {PRIMARY_HELPLINE_NUMBER} is free, 24x7, in your language, if you'd like a real person to talk to tonight. Can you tell me a bit more about what's happening?")
HANDOFF_ACK = ("Okay. I've asked a person from our team to reach out to you - that is a real human, and it may take a little while.\n"
               f"While you wait, {PRIMARY_HELPLINE_NAME} {PRIMARY_HELPLINE_NUMBER} is free and answers 24x7. I'll stay here too.")
DELETE_ACK = "Done. Everything you shared with me has been deleted. If you ever want to talk again, I'll start fresh, and I'm still here."
NUDGE_LINE = "We've been talking for a while now - would a short pause help? Some water, a stretch, maybe a step outside. I'll be right here afterwards."
REASK_AGE = "I just need a quick yes: are you 18 or older and okay to continue? Reply YES, or tell me your age."


class Companion:
    def __init__(self, settings: Settings, db: Session, llm: CompanionLLM | None, risk_gate: RiskGate, guard: OutputGuard):
        self.settings = settings
        self.db = db
        self.llm = llm
        self.gate = risk_gate
        self.guard = guard
        self.flow = CrisisFlow(handoff_instruction=settings.handoff_instruction)

    # ------------------------------------------------------------------ public entry
    def handle(self, external_id: str, text: str, now: datetime | None = None) -> Reply:
        now = now or utcnow()
        text = (text or "").strip()
        user = get_or_create_user(self.db, external_id)
        history = recent_messages(self.db, user, self.settings.history_turns)
        elapsed_min, new_session = self._touch_session(user, now)
        flags: list[str] = []
        if new_session:
            cs0 = CrisisState.from_dict(user.get_crisis_state())
            if not cs0.active and cs0.stage:
                cs0.stage = ""            # a resolved flow does not carry into the next session; a renewed signal restarts it
                user.set_crisis_state(cs0.to_dict())

        # --- commands -------------------------------------------------------------------
        if _DELETE_CMD.match(text):
            delete_user_data(self.db, external_id)
            return Reply(text=DELETE_ACK, mode="companion")
        if _HUMAN_CMD.match(text):
            self._queue_review(user, NONE, ["user_requested_human"], text, HANDOFF_ACK, True)
            return self._finish(user, text, HANDOFF_ACK, Reply(text=HANDOFF_ACK, mode="handoff", handoff_requested=True, flags=["user_requested_human"]), now)

        mood = _MOOD.search(text)
        if mood:
            score = int(mood.group(1) or mood.group(2))
            if 1 <= score <= 10:
                self.db.add(MoodLog(user_id=user.id, score=float(score), note=text[:120]))
                flags.append("mood_logged")

        # --- risk gate (always, even during onboarding) ---------------------------------------
        risk = self.gate.assess(text, history)
        minor = risk.has("minor_indicator") or user.minor_flagged

        # --- age gate + consent ---------------------------------------------------------------
        if not user.age_confirmed:
            if not user.onboarding_sent:
                user.onboarding_sent = True
                if risk.level == NONE and not minor:
                    msg = render(AGE_CONSENT_MESSAGE, companion_name=self.settings.companion_name)
                    return self._finish(user, text, msg, Reply(text=msg, mode="onboarding"), now)
            else:
                age = _AGE.search(text)
                age_n = int(age.group(1)) if age else None
                if minor or _NO.match(text) or (age_n is not None and 10 <= age_n < 18):
                    minor = True
                elif _YES.match(text) or (age_n is not None and age_n >= 18):
                    user.age_confirmed, user.consent_at = True, now
                    if risk.level == NONE:
                        user.opened = True
                        msg = render(OPENING_MESSAGE, user_name=user.name or "there", companion_name=self.settings.companion_name)
                        return self._finish(user, text, msg, Reply(text=msg, mode="onboarding"), now)
                elif risk.level == NONE:
                    return self._finish(user, text, REASK_AGE, Reply(text=REASK_AGE, mode="onboarding"), now)
            # a flagged message during onboarding falls through: safety first, onboarding resumes later

        if minor and risk.level != IMMINENT:
            user.minor_flagged = True
            turn = self.flow.minor_script()
            self._queue_review(user, max_level(risk.level, ELEVATED), risk.categories + ["minor_indicator"], text, turn.text, True)
            return self._finish(user, text, turn.text, Reply(text=turn.text, mode="minor", risk_level=risk.level, categories=risk.categories,
                                                              handoff_requested=True, flags=["minor_suspected"] + flags), now)

        # --- router -----------------------------------------------------------------------------
        cs = CrisisState.from_dict(user.get_crisis_state())
        same_session_support = cs.stage == SUPPORT and not cs.active
        if risk.level == IMMINENT or cs.active or (risk.level == ELEVATED and not same_session_support):
            return self._crisis_turn(user, cs, text, risk, history, flags, minor, now)

        # --- companion LLM ----------------------------------------------------------------------
        return self._companion_turn(user, cs, text, risk, history, flags, elapsed_min, now)

    # ------------------------------------------------------------------ crisis path
    def _crisis_turn(self, user: User, cs: CrisisState, text: str, risk: RiskAssessment, history: list[dict], flags: list[str], minor: bool, now: datetime) -> Reply:
        turn, cs = self.flow.step(cs, text, risk)
        level = max_level(risk.level, turn.level)
        if turn.stage == HUMAN_CONFIRMED:
            cs.active = False            # companion resumes next turn with a follow-up instruction
        reply_text, regenerated, used_llm, violations = self._word(turn, history, text, level)
        if minor and "1098" not in reply_text:
            reply_text += "\nIf you're under 18, Childline 1098 is free and 24x7 as well."
        user.set_crisis_state(cs.to_dict())
        user.followup_due = True
        user.last_risk = level
        if cs.safety_plan:
            plan = user.get_safety_plan()
            plan.update(cs.safety_plan)
            user.set_safety_plan(plan)
        mode = "safety_plan" if any(f.startswith("safety_plan") for f in turn.flags) else "crisis"
        self._queue_review(user, level, risk.categories, text, reply_text, turn.handoff_requested)
        r = Reply(text=reply_text, mode=mode, risk_level=level, categories=risk.categories, handoff_requested=turn.handoff_requested,
                  flags=flags + turn.flags, guard_violations=violations, crisis_stage=turn.stage, llm_used=used_llm, regenerated=regenerated)
        return self._finish(user, text, reply_text, r, now, mode=mode, level=level)

    def _word(self, turn: CrisisTurn, history: list[dict], text: str, level: str) -> tuple[str, bool, bool, list[str]]:
        """Let the LLM reword a scripted crisis message if allowed; the script is the fallback."""
        if not (self.llm and self.settings.llm_words_crisis and turn.allow_llm_wording):
            return turn.text, False, False, []
        msgs = history + [{"role": "user", "content": text or "(silence)"}]
        worded = self.llm.word_crisis(turn.text, turn.wording_instruction, msgs)
        if not worded:
            return turn.text, False, True, ["llm_unavailable"]
        g = self.guard.check(worded, level, text, crisis_active=True)
        missing = [m for m in turn.must_include if m not in worded]
        if g.passed and not missing:
            return worded, False, True, []
        return turn.text, True, True, g.violations + ([f"missing:{m}" for m in missing])

    # ------------------------------------------------------------------ companion path
    def _companion_turn(self, user: User, cs: CrisisState, text: str, risk: RiskAssessment, history: list[dict], flags: list[str], elapsed_min: float, now: datetime) -> Reply:
        instruction = self._turn_instruction(user, cs, risk, elapsed_min, text)
        if _ASKS_IF_HUMAN.search(text):
            flags.append("asks_if_human")
        system = self._system(user, instruction)
        messages = history + [{"role": "user", "content": text}]
        used_llm, regenerated, violations = False, False, []
        reply_text = ""
        out = self.llm.respond(system, messages) if self.llm else None
        if out is not None:
            used_llm = True
            # Second line of defence: the companion model saw something the gate did not.
            if out.risk_observed == IMMINENT or (out.risk_observed == ELEVATED and risk.level == NONE):
                esc = RiskAssessment(level=out.risk_observed, categories=sorted(set(risk.categories) | set(out.flags)), evidence=["companion_llm"], source="companion_llm")
                flags.append("escalated_by_companion_llm")
                return self._crisis_turn(user, cs, text, esc, history, flags, False, now)
            g = self.guard.check(out.reply, risk.level, text)
            if not g.passed:
                violations = list(g.violations)
                regenerated = True
                fixed_system = system + "\n\n## MANDATORY CORRECTION (your previous draft was rejected)\n" + g.fix_instruction
                out2 = self.llm.respond(fixed_system, messages)
                if out2 is not None:
                    g2 = self.guard.check(out2.reply, risk.level, text)
                    if g2.passed:
                        out = out2
                    else:
                        violations += g2.violations
                        out = None
                else:
                    out = None
        if out is None:
            reply_text = FALLBACK_ELEVATED if risk.level != NONE else FALLBACK_COMPANION
            r = Reply(text=reply_text, mode="fallback", risk_level=risk.level, categories=risk.categories, flags=flags,
                      guard_violations=violations, llm_used=used_llm, regenerated=regenerated, fallback_used=True)
            return self._finish(user, text, reply_text, r, now, level=risk.level)

        reply_text = out.reply.strip()
        self._apply_memory(user, out.memory_updates)
        mode = out.mode_suggestion if out.mode_suggestion in ("companion", "skill", "screener", "wind_down") else "companion"
        if elapsed_min >= self.settings.session_nudge_minutes and not user.nudged_this_session and risk.level == NONE:
            user.nudged_this_session = True
            flags.append("long_session")
            if len([l for l in reply_text.splitlines() if l.strip()]) < self.settings.reply_max_lines:
                reply_text += "\n" + NUDGE_LINE
            mode = "wind_down"
        if user.followup_due and risk.level == NONE:
            user.followup_due = False          # the follow-up instruction was delivered this turn
        r = Reply(text=reply_text, mode=mode, risk_level=risk.level, categories=risk.categories, handoff_requested=bool(out.handoff_requested),
                  flags=flags + [f for f in out.flags if f not in flags], guard_violations=violations, llm_used=True, regenerated=regenerated)
        if out.handoff_requested:
            self._queue_review(user, risk.level, risk.categories, text, reply_text, True)
        return self._finish(user, text, reply_text, r, now, mode=mode, level=risk.level)

    # ------------------------------------------------------------------ helpers
    def _system(self, user: User, instruction: str) -> str:
        s = self.settings
        return render(
            SYSTEM_PROMPT,
            companion_name=s.companion_name, user_name=user.name or "friend", language=user.language or s.default_language,
            what_helps=", ".join(user.get_list("what_helps")), supports=", ".join(user.get_list("supports")),
            safety_plan=json.dumps(user.get_safety_plan(), ensure_ascii=False) if user.get_safety_plan() else "",
            mood_summary=mood_summary(self.db, user), screener_summary="(none yet; screeners arrive in Phase 2)",
            spiritual_pref=user.spiritual_pref, primary_helpline_name=PRIMARY_HELPLINE_NAME, primary_helpline_number=PRIMARY_HELPLINE_NUMBER,
            handoff_instruction=s.handoff_instruction, special_scripts="(handled by the orchestrator's crisis flow; you will be given the script to word)",
            partner_counsellor_offer=s.partner_counsellor_offer, helpline_directory=directory_text("ALL"), turn_instruction=instruction,
        )

    def _turn_instruction(self, user: User, cs: CrisisState, risk: RiskAssessment, elapsed_min: float, text: str) -> str:
        parts = [f"Risk level for this turn: {risk.level}." if risk.level == NONE else f"Risk level for this turn: {risk.level} (categories: {', '.join(risk.categories)})."]
        if risk.level == ELEVATED:
            parts.append("Stay supportive, do not end or refuse, offer Tele-MANAS 14416 once, and gently keep the safety questions in view. No lists of tips.")
        if user.followup_due or cs.stage in (SUPPORT, HUMAN_CONFIRMED) or cs.human_contact_confirmed:
            parts.append("This person had elevated or imminent risk recently. Before anything else, check in gently about how they have been since, and whether they reached the person or helpline they planned to.")
        if risk.has("psychosis"):
            parts.append("Possible psychosis markers: do not agree with or argue against the belief; stay with the feeling; suggest a trusted person or doctor.")
        if elapsed_min >= self.settings.session_nudge_minutes:
            parts.append(f"The session has lasted about {int(elapsed_min)} minutes: gently suggest a pause (water, stretch, sleep) and offer to continue later, while remaining available.")
        if _ASKS_IF_HUMAN.search(text):
            parts.append("The user asked whether you are human: say plainly and immediately that you are an AI.")
        parts.append("Return ONLY the JSON object described under Output.")
        return " ".join(parts)

    def _apply_memory(self, user: User, updates: dict | None) -> None:
        if not updates:
            return
        for key in ("what_helps", "supports", "triggers"):
            vals = updates.get(key) or []
            if isinstance(vals, list):
                user.add_to_list(key, [str(v) for v in vals])

    def _touch_session(self, user: User, now: datetime) -> tuple[float, bool]:
        last = user.last_message_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=now.tzinfo)
        new_session = False
        if user.session_started_at is None or last is None or (now - last) > timedelta(minutes=self.settings.session_gap_minutes):
            user.session_started_at = now
            user.nudged_this_session = False
            new_session = True
        started = user.session_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=now.tzinfo)
        user.last_message_at = now
        return (now - started).total_seconds() / 60.0, new_session

    def _queue_review(self, user: User, level: str, cats: list[str], user_text: str, reply: str, handoff: bool) -> None:
        self.db.add(ReviewItem(user_id=user.id, risk_level=level, categories=json.dumps(cats), user_text=user_text, reply_text=reply, handoff_requested=handoff))

    def _finish(self, user: User, user_text: str, reply_text: str, r: Reply, now: datetime, mode: str | None = None, level: str = NONE) -> Reply:
        self.db.add(Message(user_id=user.id, role="user", content=user_text, risk_level=level, mode=mode or r.mode, created_at=now))
        self.db.add(Message(user_id=user.id, role="assistant", content=reply_text, risk_level=level, mode=mode or r.mode, created_at=now))
        self.db.commit()
        return r


# --------------------------------------------------------------------------------------------
# Factory for real use
# --------------------------------------------------------------------------------------------
def build_companion(settings: Settings, db: Session, live: bool = True) -> Companion:
    """Wire everything. live=False gives rules-only gate/guard and no companion model (scripted fallbacks)."""
    if not live:
        return Companion(settings, db, None, RiskGate(None), OutputGuard(None, settings.reply_max_lines))
    from .guard import ClaudeGuard
    from .llm import make_client
    from .risk import ClaudeRiskClassifier

    client = make_client(settings)
    gate = RiskGate(ClaudeRiskClassifier(client, settings.classifier_model, settings.effort) if settings.use_llm_classifier else None)
    guard = OutputGuard(ClaudeGuard(client, settings.guard_model, settings.effort) if settings.use_llm_guard else None, settings.reply_max_lines)
    return Companion(settings, db, ClaudeCompanionLLM(client, settings.companion_model, settings.effort), gate, guard)
