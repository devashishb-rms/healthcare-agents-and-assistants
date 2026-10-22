"""Scripted crisis flow. A fixed state machine; the LLM may only choose the words.

Design (plan section 2.5, crisis protocol):
  IMMINENT track:  PRESENCE_AND_SAFETY -> (EMERGENCY if they have acted) -> HELPLINE -> MEANS_SAFETY (if a means was
                   mentioned) -> REASONS_FOR_LIVING -> CHECK_IN ... until human contact is confirmed -> HUMAN_CONFIRMED.
                   handoff_requested is True from the first IMMINENT turn and never cleared by this module.
  ELEVATED track:  ACKNOWLEDGE -> SAFETY_Q1 (thoughts of ending life?) -> SAFETY_Q2 (any plan?) -> SAFETY_PLAN (six
                   items, one per turn) -> OFFER_HELP -> SUPPORT (back to the companion with an elevated instruction).
                   A "yes" to a plan, or any new IMMINENT signal, jumps to the IMMINENT track.
  Special scripts: harm_to_others, abuse_victim, medical_emergency / overdose_substance, psychosis,
                   eating_disorder_purge, minor_indicator. Each returns the matching script and the human route.

Every `CrisisTurn` carries the scripted text (always safe to send as-is), the numbers that MUST survive any
rewording, and whether rewording is allowed at all (never for the emergency step).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from .risk import ELEVATED, IMMINENT, NONE, RiskAssessment

# --------------------------------------------------------------------------------------------
# Helpline directory: the ONLY numbers the product may ever give.
# --------------------------------------------------------------------------------------------
HELPLINES: list[dict] = [
    {"id": "tele_manas", "name": "Tele-MANAS", "numbers": ["14416", "1-800-891-4416"], "region": "IN", "hours": "24x7, free, 20+ Indian languages", "kind": "mental_health", "primary": True},
    {"id": "emergency_in", "name": "Emergency services", "numbers": ["112"], "region": "IN", "hours": "24x7", "kind": "emergency", "primary": True},
    {"id": "ambulance_in", "name": "Ambulance", "numbers": ["108"], "region": "IN", "hours": "24x7", "kind": "emergency"},
    {"id": "vandrevala", "name": "Vandrevala Foundation", "numbers": ["+91 9999 666 555"], "region": "IN", "hours": "24x7, free", "kind": "mental_health"},
    {"id": "icall", "name": "iCall (TISS)", "numbers": ["9152987821"], "region": "IN", "hours": "Mon-Sat 10am-8pm", "kind": "mental_health"},
    {"id": "aasra", "name": "AASRA", "numbers": ["+91-22-27546669"], "region": "IN", "hours": "24x7", "kind": "mental_health"},
    {"id": "women_in", "name": "Women's helpline", "numbers": ["181"], "region": "IN", "hours": "24x7", "kind": "abuse_women"},
    {"id": "childline_in", "name": "Childline", "numbers": ["1098"], "region": "IN", "hours": "24x7", "kind": "abuse_children"},
    {"id": "lifeline_us", "name": "988 Suicide & Crisis Lifeline", "numbers": ["988"], "region": "US", "hours": "24x7", "kind": "mental_health"},
    {"id": "samaritans_uk", "name": "Samaritans", "numbers": ["116 123"], "region": "UK", "hours": "24x7, free", "kind": "mental_health"},
]

PRIMARY_HELPLINE_NAME = "Tele-MANAS"
PRIMARY_HELPLINE_NUMBER = "14416"


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def directory_digit_set() -> set[str]:
    """All allowed numbers as bare digit strings, with and without the +91 country code."""
    out: set[str] = set()
    for h in HELPLINES:
        for n in h["numbers"]:
            d = _digits(n)
            out.add(d)
            if d.startswith("91") and len(d) > 10:
                out.add(d[2:])
            elif len(d) == 10 and h["region"] == "IN":
                out.add("91" + d)
    return out


def directory_text(region: str = "IN") -> str:
    lines = []
    for h in HELPLINES:
        if h["region"] in (region, "IN") or region == "ALL":
            lines.append(f"- {h['name']}: {' / '.join(h['numbers'])} ({h['hours']})")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------
# Yes / no / "I did something" parsing (English, Hinglish, Devanagari)
# --------------------------------------------------------------------------------------------
_YES = re.compile(r"^\W*(yes|yeah|yep|ya|yup|haan|ha|han|hn|ji|ji haan|haa|हाँ|हां|जी|sure|ok|okay|theek hai|thik hai|done|called|i did|i have|kar liya|kar diya|kiya|kar li|ho gaya|baat ki|call kiya|call kar liya)\b", re.I)
_NO = re.compile(r"^\W*(no|nope|nah|nahi|nhi|na|नहीं|नही|not yet|abhi nahi|haven'?t|didn'?t|i'?m safe|im safe|safe hoon|safe hu|kuch nahi kiya|nothing)\b", re.I)
_SAFE = re.compile(r"\b(i'?m safe|im safe|i am safe|safe (hoon|hu|hun)|haven'?t (done|taken|hurt)|didn'?t (do|take|hurt)|not (done|taken|hurt) anything|kuch (nahi|nhi) (kiya|liya|khaya)|nothing yet|no i haven'?t|theek hoon|thik hoon|main theek|मैं ठीक|कुछ नहीं किया)\b", re.I)
_DID_HARM = re.compile(r"\b(i (took|swallowed|ate|drank|cut|slit|hurt|did)|yes i (did|have|took|cut)|i('ve| have) (taken|swallowed|cut|hurt|done)|kha li|kha liya|pee li|pi li|kaat liya|kat liya|kar liya|haan kiya|yes|haan|ha|ji|हाँ|हां|खा ली|पी ली|काट लिया|कर लिया|bleeding|khoon)\b", re.I)
_HUMAN_CONTACT = re.compile(r"\b(i called|called them|calling (them|now|14416|tele|vandrevala)|on the phone|talking to (them|someone|a counsellor|a counselor|my (mom|dad|mother|father|brother|sister|friend|wife|husband|roommate))|they (are|'re) (coming|here|with me|on the line)|ambulance (is )?(here|coming|called)|(my|a) (friend|neighbour|neighbor|roommate|mom|dad|mother|father|brother|sister|wife|husband) is (here|with me|coming)|someone is (here|with me)|at the hospital|in the hospital|reached hospital|call kar (liya|diya|rahi hoon|raha hoon)|phone kiya|baat kar (li|liya|rahi|raha)|(mummy|mama|papa|bhai|didi|dost|friend|roommate) (aa (gaye|gayi|gaya|rahe|rahi)|saath (hai|hain)|paas (hai|hain)|yahan (hai|hain))|hospital (me|mein) (hoon|hu|hun)|फोन किया|बात कर (ली|लिया|रही|रहा)|साथ (है|हैं)|अस्पताल)\b", re.I)
_ESCALATE_WORDS = re.compile(r"\b(yes|yeah|haan|ha|hn|ji|हाँ|हां|i have a plan|plan hai|soch liya|decided|kar hi dunga|kar hi dungi)\b", re.I)
_REFUSAL = re.compile(r"^\W*(no|nope|nahi|nhi|na|skip|pass|nothing|none|kuch nahi|don'?t know|dont know|idk|pata nahi|नहीं|कुछ नहीं)\W*$", re.I)

# Stages
PRESENCE_AND_SAFETY = "presence_and_safety"
EMERGENCY = "emergency"
HELPLINE = "helpline"
MEANS_SAFETY = "means_safety"
REASONS_FOR_LIVING = "reasons_for_living"
CHECK_IN = "check_in"
HUMAN_CONFIRMED = "human_confirmed"
ACKNOWLEDGE = "acknowledge"
SAFETY_Q1 = "safety_q1"
SAFETY_Q2 = "safety_q2"
SAFETY_PLAN = "safety_plan"
OFFER_HELP = "offer_help"
SUPPORT = "support"
RESOLVED = "resolved"

SAFETY_PLAN_ITEMS = [
    ("warning_signs", "What are the first signs, in your body or your thoughts, that tell you a hard moment is starting?"),
    ("self_soothing", "When it starts, what is one small thing you can do by yourself that has helped even a little before - music, a walk, washing your face, a prayer, anything?"),
    ("distractions", "Which people or places take your mind off things, even for a while - a friend, a chai stall, a temple, a park, a cousin's house?"),
    ("people_for_help", "Who is one person you could message or call and say 'I'm not okay right now'? A name or just 'my sister' is fine."),
    ("professionals", "For the professionals-and-helplines part, I'll put Tele-MANAS 14416 (free, 24x7). Is there a doctor or counsellor you've seen, or shall I note 'find one' for now?"),
    ("safe_space", "Last one: is there anything around you that it would be safer to put away or give to someone for a while, just for now?"),
]

_MEANS_WORDS = re.compile(r"\b(pills?|tablets?|goliyan|goliya|goli|dawai|rope|rassi|dupatta|blade|razor|knife|chaku|chhuri|gun|pistol|poison|zeher|zehar|phenyl|sulphas|pesticide|acid|kerosene|roof|chhat|terrace|bridge|pul|track|patri|fan|pankha|belt|insulin|wire|फंदा|रस्सी|गोली|ब्लेड|चाकू|ज़हर|जहर|छत)\b", re.I)


@dataclass
class CrisisState:
    active: bool = False
    level: str = NONE                       # IMMINENT | ELEVATED
    stage: str = ""
    turns: int = 0
    handoff_requested: bool = False
    means_mentioned: bool = False
    means_addressed: bool = False
    reasons_asked: bool = False
    helpline_offered: int = 0
    human_contact_confirmed: bool = False
    special: str = ""                       # abuse_victim | harm_to_others | medical | psychosis | eating_disorder | minor
    safety_plan: dict = field(default_factory=dict)
    plan_index: int = 0
    last_user: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "CrisisState":
        if not d:
            return cls()
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CrisisTurn:
    text: str                               # scripted, always safe to send verbatim
    stage: str
    level: str
    handoff_requested: bool
    allow_llm_wording: bool = True          # False for the emergency step: numbers, verbatim, no creativity
    must_include: list[str] = field(default_factory=list)   # substrings that must survive rewording
    wording_instruction: str = ""
    forbid_tools: bool = True               # never breathing / tips while this is active
    flags: list[str] = field(default_factory=list)


_PRIMARY = f"{PRIMARY_HELPLINE_NAME} {PRIMARY_HELPLINE_NUMBER}"


class CrisisFlow:
    """Pure state machine: step(state, user_text, risk) -> (CrisisTurn, new_state). No I/O."""

    def __init__(self, handoff_instruction: str = "Type HUMAN at any time and a person from our team will be alerted."):
        self.handoff_instruction = handoff_instruction

    # ------------------------------------------------------------------ entry
    def start(self, risk: RiskAssessment, state: CrisisState | None = None) -> CrisisState:
        s = state or CrisisState()
        s.active = True
        s.level = IMMINENT if risk.level == IMMINENT else ELEVATED
        s.turns = 0
        s.means_mentioned = s.means_mentioned or risk.has("means", "in_progress") or bool(_MEANS_WORDS.search(" ".join(risk.evidence)))
        s.special = self._special_for(risk) or s.special
        if s.level == IMMINENT:
            s.handoff_requested = True
            s.stage = EMERGENCY if risk.has("in_progress", "overdose_substance", "medical_emergency") else PRESENCE_AND_SAFETY
        else:
            s.stage = ACKNOWLEDGE
        return s

    @staticmethod
    def _special_for(risk: RiskAssessment) -> str:
        if risk.has("medical_emergency", "overdose_substance"):
            return "medical"
        if risk.has("harm_to_others"):
            return "harm_to_others"
        if risk.has("abuse_victim"):
            return "abuse_victim"
        if risk.has("psychosis"):
            return "psychosis"
        if risk.has("eating_disorder_purge"):
            return "eating_disorder"
        return ""

    # ------------------------------------------------------------------ main step
    def step(self, state: CrisisState, user_text: str, risk: RiskAssessment) -> tuple[CrisisTurn, CrisisState]:
        s = state
        if not s.active:
            s = self.start(risk, s)
        # New information can only escalate.
        if risk.level == IMMINENT and s.level != IMMINENT:
            s = self.start(risk, s)
        elif risk.level == IMMINENT and risk.has("in_progress", "overdose_substance", "medical_emergency") and s.stage not in (EMERGENCY,):
            s.stage = EMERGENCY
        if risk.has("means", "in_progress") or _MEANS_WORDS.search(user_text or ""):
            s.means_mentioned = True
        if not s.special:
            s.special = self._special_for(risk)
        s.turns += 1
        s.last_user = user_text or ""
        before = s.stage

        if s.level == IMMINENT:
            turn = self._imminent(s, user_text, risk)
        else:
            turn = self._elevated(s, user_text, risk)
        turn.handoff_requested = s.handoff_requested
        # turn.stage names the step that was just delivered; state.stage is where the flow goes next.
        return turn, s

    # ------------------------------------------------------------------ IMMINENT track
    def _imminent(self, s: CrisisState, text: str, risk: RiskAssessment) -> CrisisTurn:
        text = text or ""
        if s.stage == PRESENCE_AND_SAFETY and s.turns == 1:
            msg = ("I'm here with you, and thank you for telling me. That took courage.\n"
                   "Are you safe right now? Have you done anything to hurt yourself?")
            if risk.has("method_request"):
                msg = ("That's one thing I won't give you, and I'm not going to lecture you about it either. I'd rather stay with you.\n"
                       "Are you safe right now? Have you done anything to hurt yourself?")
            if s.special == "harm_to_others":
                msg = ("I'm here, and I'm glad you said this out loud rather than acting on it.\n"
                       "Right now, in this moment - are you safe, and is anyone near you safe? Have you hurt anyone or yourself?")
            msg += f"\nIf you'd rather talk to a person right now: {_PRIMARY}, free, 24x7. I'm staying here either way."
            return self._turn(s, msg, must=["14416"], stage=PRESENCE_AND_SAFETY,
                              instruction="Open the crisis protocol: stay present, thank them (or, for a method question, decline that part gently without lecturing), ask directly whether they are safe right now and whether they have done anything to hurt themselves, and mention Tele-MANAS 14416 once. Two short questions, nothing else.")

        if s.stage == PRESENCE_AND_SAFETY:
            if _SAFE.search(text) or (_NO.search(text) and not _DID_HARM.search(text)):
                s.stage = HELPLINE
            elif _DID_HARM.search(text) or risk.has("in_progress", "overdose_substance"):
                s.stage = EMERGENCY
            else:
                # Ambiguous: when unsure, treat as possibly having acted; give the emergency number AND move on.
                s.stage = HELPLINE
                return self._turn(s, "I may have missed it - if you have taken or done anything to hurt yourself, please call 112 (or 108 for an ambulance) right now, or ask someone near you to.\n"
                                      f"If not, I'm still here. {_PRIMARY} is free, 24x7, in your language. Can you call them now, or shall I give you another option?",
                                  must=["112", "108", "14416"], stage=HELPLINE, instruction="Ambiguous answer to the safety question: give 112/108 in case they have acted, then offer Tele-MANAS 14416 and ask if they can call now.")

        if s.stage == EMERGENCY:
            s.stage = HELPLINE
            msg = ("Please call 112 (or 108 for an ambulance) now, or ask someone near you to call. I'll stay with you while you do.\n"
                   "112. Or 108. Can you do that right now, or tell me who is near you?")
            if s.special == "medical":
                msg = ("This needs a doctor right now. Please call 112 (or 108 for an ambulance) now, or ask someone near you to call. I'll stay with you.\n"
                       "112. Or 108. If you can, unlock the door and tell me who is near you.")
            return CrisisTurn(text=msg, stage=EMERGENCY, level=IMMINENT, handoff_requested=True, allow_llm_wording=False,
                              must_include=["112", "108"], flags=["emergency"])

        if s.stage == HELPLINE:
            if _HUMAN_CONTACT.search(text):
                return self._confirm_human(s)
            s.helpline_offered += 1
            if s.means_mentioned and not s.means_addressed:
                s.stage = MEANS_SAFETY
            elif not s.reasons_asked:
                s.stage = REASONS_FOR_LIVING
            else:
                s.stage = CHECK_IN
            if s.helpline_offered == 1:
                msg = (f"Thank you. {_PRIMARY} is free, 24x7, and in your language. Can you call them now, or shall I give you another option?\n"
                       f"There is also Vandrevala Foundation +91 9999 666 555, any time. {self.handoff_instruction}")
                if s.special == "harm_to_others":
                    msg = (f"Thank you for being honest. Feelings this strong are a sign you need a person with you right now. {_PRIMARY} is free, 24x7, and they talk about anger and urges too. Can you call them now?\n"
                           f"If you feel you might act, step away from where the other person is and call 112. {self.handoff_instruction}")
                must = ["14416", "9999 666 555"] if s.special != "harm_to_others" else ["14416", "112"]
                return self._turn(s, msg, must=must, stage=HELPLINE, instruction="Connect to a human: offer Tele-MANAS 14416 as primary, a second line, and the in-app human handoff. One question: can they call now, or want another option.")
            msg = (f"I'm still here. {_PRIMARY} or Vandrevala +91 9999 666 555 - either one, right now, is a real person who can help more than I can.\n"
                   "Which one feels easier to try? I'll wait.")
            return self._turn(s, msg, must=["14416", "9999 666 555"], stage=HELPLINE, instruction="Second offer of the helplines, gently, one question.")

        if s.stage == MEANS_SAFETY:
            if _HUMAN_CONTACT.search(text):
                return self._confirm_human(s)
            s.means_addressed = True
            s.stage = REASONS_FOR_LIVING if not s.reasons_asked else CHECK_IN
            msg = ("Can I ask one thing? Whatever you were thinking of using - could you put it in another room, or give it to someone, just for tonight? Not forever. Just for now.\n"
                   "I'll stay here while you do.")
            return self._turn(s, msg, stage=MEANS_SAFETY, instruction="Means safety: ask them to put the object/means in another room or give it to someone, just for tonight. Do NOT name or discuss the method itself.")

        if s.stage == REASONS_FOR_LIVING:
            if _HUMAN_CONTACT.search(text):
                return self._confirm_human(s)
            s.reasons_asked = True
            s.stage = CHECK_IN
            msg = ("Thank you. Can I ask - is there one person, or an animal, or even a small task or belief that still matters to you today? Even something tiny.\n"
                   f"And if talking to a real person feels possible, {_PRIMARY} is still there, right now.")
            return self._turn(s, msg, must=["14416"], stage=REASONS_FOR_LIVING, instruction="Reasons for living: ask about one person, animal, task or belief that still matters today. Repeat the Tele-MANAS number once.")

        # CHECK_IN loop
        if _HUMAN_CONTACT.search(text):
            return self._confirm_human(s)
        s.stage = CHECK_IN
        reflect = ""
        if s.turns % 2 == 0:
            reflect = "Thank you for staying with me and for telling me that. "
        msg = (f"{reflect}I'm still here, and I'm not going anywhere. How are you doing right now, this minute?\n"
               f"Have you been able to call {_PRIMARY}, or is there someone near you who could sit with you? {self.handoff_instruction}")
        return self._turn(s, msg, must=["14416"], stage=CHECK_IN, instruction="Keep checking in: reflect what they said in their words, ask how they are right now, ask whether they have reached Tele-MANAS or a person nearby. Do not end, do not offer exercises.")

    def _confirm_human(self, s: CrisisState) -> CrisisTurn:
        s.stage = HUMAN_CONFIRMED
        s.human_contact_confirmed = True
        msg = ("I'm really glad you're not alone with this now. Stay with them, and let them help.\n"
               "I'll be here afterwards too, whenever you want to talk. You did a hard, brave thing today.")
        return self._turn(s, msg, stage=HUMAN_CONFIRMED, instruction="They have reached a human. Affirm, encourage them to stay with that person, remain available. No advice.")

    # ------------------------------------------------------------------ ELEVATED track
    def _elevated(self, s: CrisisState, text: str, risk: RiskAssessment) -> CrisisTurn:
        text = text or ""
        sp = s.special
        if s.stage == ACKNOWLEDGE:
            s.stage = SAFETY_Q1
            if sp == "abuse_victim":
                msg = ("I'm really glad you told me. What's happening to you is not okay, and it is not your fault.\n"
                       "Are you safe right now, this minute? If you're in danger, 112 is there any time, and the women's helpline 181 (or 1098 for anyone under 18) can help you plan next steps.\n"
                       "Can I also ask - have you had any thoughts of ending your life?")
                return self._turn(s, msg, must=["112", "181", "1098"], stage=ACKNOWLEDGE, instruction="Abuse disclosure: validate, say it is not their fault, check immediate safety, give 112 / 181 / 1098, then ask the first safety question.", flags=["abuse"])
            if sp == "harm_to_others":
                msg = ("Thank you for saying that to me instead of acting on it. Anger that big usually sits on top of a lot of hurt.\n"
                       "Right now - are you and the other person safe? Can you be in a different room from them for a while?\n"
                       "And can I ask: have you had thoughts of ending your own life too?")
                return self._turn(s, msg, stage=ACKNOWLEDGE, instruction="Harm-to-others disclosure: thank them for saying it, check safety of both, suggest physical distance, ask the first safety question.", flags=["harm_to_others"])
            if sp == "psychosis":
                msg = ("That sounds frightening and exhausting to live with, and I'm glad you're telling me.\n"
                       "I can't see what you're seeing, so I won't pretend to know what's true - but I do know you deserve to feel safe. Is there someone you trust who could be with you, or a doctor you've seen before?\n"
                       "Can I also check: have you had any thoughts of hurting yourself or ending your life?")
                return self._turn(s, msg, stage=ACKNOWLEDGE, instruction="Possible psychosis: stay with the feeling, do not agree or argue with the belief, suggest a trusted person or doctor, ask the first safety question.", flags=["psychosis_markers"])
            if sp == "eating_disorder":
                msg = ("Thank you for trusting me with that. What you're describing is hard on the body and on the heart, and it isn't something you have to manage alone.\n"
                       "A doctor can check you're physically okay without judgement, and Tele-MANAS 14416 is free if you want to talk to someone today.\n"
                       "Can I ask - have you had any thoughts of ending your life?")
                return self._turn(s, msg, must=["14416"], stage=ACKNOWLEDGE, instruction="Eating-disorder purging disclosure: validate, route to a doctor and Tele-MANAS 14416, ask the first safety question. No food or weight advice.", flags=["eating_disorder"])
            msg = ("Thank you for saying that - it takes courage. It sounds like things have felt very heavy, maybe for a while.\n"
                   "Can I ask you something directly, because I care about the answer: have you been having thoughts of ending your life?")
            return self._turn(s, msg, stage=ACKNOWLEDGE, instruction="Elevated risk: acknowledge courage, reflect the pain in their words, then ask the first safety question (thoughts of ending life?). One question.")

        if s.stage == SAFETY_Q1:
            if _ESCALATE_WORDS.search(text) and not _NO.search(text):
                s.stage = SAFETY_Q2
                msg = ("Thank you for being honest with me. I'm here.\n"
                       "Have you thought about how you would do it, or made any kind of plan?")
                return self._turn(s, msg, stage=SAFETY_Q2, instruction="They said yes to thoughts of ending life. Ask the second safety question: any plan or thought about how. One question, calm.")
            s.stage = SAFETY_PLAN
            s.plan_index = 0
            msg = ("I'm glad you told me. Those thoughts can come and go, and you don't have to carry them alone.\n"
                   "Would it be okay if we put together a small plan for the hard moments, one piece at a time? "
                   + SAFETY_PLAN_ITEMS[0][1])
            return self._turn(s, msg, stage=SAFETY_PLAN, instruction="No active thoughts (or unclear): propose building a simple safety plan together and ask the first item (warning signs).", flags=["safety_plan"])

        if s.stage == SAFETY_Q2:
            if _ESCALATE_WORDS.search(text) and not _NO.search(text):
                # A plan means IMMINENT: switch tracks.
                s.level = IMMINENT
                s.handoff_requested = True
                s.stage = HELPLINE
                msg = (f"Thank you for telling me. I'm staying right here with you.\n"
                       f"Because you have a plan, I want you to talk to a real person tonight. {_PRIMARY} is free, 24x7, in your language. Can you call them now, or shall I give you another option? {self.handoff_instruction}")
                return self._turn(s, msg, must=["14416"], stage=HELPLINE, instruction="They disclosed a plan: this is now imminent risk. Stay present, say a human needs to be involved tonight, offer Tele-MANAS 14416 and the in-app handoff.", flags=["escalated_to_imminent"])
            s.stage = SAFETY_PLAN
            s.plan_index = 0
            msg = ("Thank you. I'm glad there's no plan, and I still take the thoughts seriously.\n"
                   "Could we make a small plan together for the hard moments, one piece at a time? "
                   + SAFETY_PLAN_ITEMS[0][1])
            return self._turn(s, msg, stage=SAFETY_PLAN, instruction="No plan: propose a simple safety plan and ask the first item (warning signs).", flags=["safety_plan"])

        if s.stage == SAFETY_PLAN:
            key, _q = SAFETY_PLAN_ITEMS[min(s.plan_index, len(SAFETY_PLAN_ITEMS) - 1)]
            if text.strip() and not _REFUSAL.match(text.strip()):
                s.safety_plan[key] = text.strip()[:300]
            s.plan_index += 1
            if s.plan_index < len(SAFETY_PLAN_ITEMS):
                nxt = SAFETY_PLAN_ITEMS[s.plan_index][1]
                must = ["14416"] if SAFETY_PLAN_ITEMS[s.plan_index][0] == "professionals" else []
                return self._turn(s, "Got it, I've noted that. " + nxt, must=must, stage=SAFETY_PLAN, instruction=f"Safety plan step {s.plan_index + 1} of 6: acknowledge their answer in a few words and ask exactly this next item.", flags=["safety_plan"])
            s.stage = OFFER_HELP
            msg = ("That's a real plan now, and it's yours - I'll keep it and we can revisit it any time.\n"
                   f"One more thing: talking to a professional about how heavy things have felt could genuinely help. {_PRIMARY} is free, 24x7. Would you be open to calling them this week, or to me helping you find a counsellor?")
            return self._turn(s, msg, must=["14416"], stage=OFFER_HELP, instruction="Safety plan complete: affirm, offer Tele-MANAS 14416 and a professional, one question.", flags=["safety_plan_complete"])

        if s.stage == OFFER_HELP:
            s.stage = SUPPORT
            s.active = False       # back to the companion, with an elevated instruction for the next sessions
            msg = ("Okay. Whatever you decide, I'm here, and I'll check in with you next time about how you're doing.\n"
                   "For now - what would feel most supportive in the next hour: just talking, or trying one small thing together?")
            return self._turn(s, msg, stage=SUPPORT, instruction="Close the elevated flow warmly, promise a follow-up next session, hand back to supportive conversation. One question.", flags=["elevated_followup"])

        s.active = False
        return self._turn(s, "I'm here. Tell me more about what's going on for you right now.", stage=SUPPORT, instruction="Return to supportive conversation.")

    # ------------------------------------------------------------------ specials outside the risk tracks
    def minor_script(self) -> CrisisTurn:
        msg = ("Thank you for telling me. I'm an AI companion built for adults, so I'm not the right support for you - but you deserve real support, today.\n"
               "Childline 1098 is free, 24x7, and for anyone under 18. Tele-MANAS 14416 is also free. If you're in danger right now, call 112.\n"
               "Please also tell one adult you trust - a parent, teacher, or school counsellor. You matter.")
        return CrisisTurn(text=msg, stage="minor", level=NONE, handoff_requested=True, allow_llm_wording=False,
                          must_include=["1098", "14416", "112"], flags=["minor_suspected"])

    def medical_script(self) -> CrisisTurn:
        msg = ("This sounds like it needs a doctor right now. Please call 112 (or 108 for an ambulance), or ask someone near you to.\n"
               "112. Or 108. I'll stay here - tell me who is with you.")
        return CrisisTurn(text=msg, stage=EMERGENCY, level=IMMINENT, handoff_requested=True, allow_llm_wording=False,
                          must_include=["112", "108"], flags=["medical"])

    # ------------------------------------------------------------------ helpers
    def _turn(self, s: CrisisState, text: str, must: list[str] | None = None, instruction: str = "", flags: list[str] | None = None, stage: str = "") -> CrisisTurn:
        return CrisisTurn(text=text, stage=stage or s.stage, level=s.level, handoff_requested=s.handoff_requested,
                          allow_llm_wording=True, must_include=must or [], wording_instruction=instruction,
                          forbid_tools=True, flags=flags or [])
