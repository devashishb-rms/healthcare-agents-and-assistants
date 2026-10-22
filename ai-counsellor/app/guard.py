"""Post-turn output guard.

Layer 1: regex hard checks that run on every draft reply (cannot be prompted away).
Layer 2: claude-haiku-5-5 with the guard prompt from the plan (JSON: pass / violations / fix_instruction).
Either layer failing fails the turn; the orchestrator then regenerates once with the fix instruction and otherwise
sends a scripted safe fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .crisis import directory_digit_set, directory_text
from .prompts import GUARD_PROMPT, GUARD_SCHEMA
from .risk import ELEVATED, IMMINENT, NONE


@dataclass
class GuardResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    fix_instruction: str = ""
    source: str = "rules"

    def __bool__(self) -> bool:
        return self.passed


_DIAGNOSIS = [
    re.compile(r"\b(you|aap|aapko|tum|tumhe|tumko) (have|are|'re|ko|mein|me|are suffering from|suffer from|might have|may have|probably have|definitely have|clearly have|seem to have|sound like you have|are showing signs of|are a|are an|hai|ho) (clinical(ly)? |major |severe |mild |moderate |classic |textbook |chronic )?(depress(ed|ion|ive)|bipolar|schizophreni\w*|adhd|add\b|autis(m|tic)|asperger|ocd|obsessive|borderline|bpd|ptsd|anxiety disorder|generalised anxiety|generalized anxiety|gad\b|panic disorder|psychosis|psychotic|an? eating disorder|anorexi\w*|bulimi\w*|personality disorder|manic|mania|dissociat\w*|narcissis\w*|sociopath|psychopath)", re.I),
    re.compile(r"\b(this is|that is|that's|this sounds like|sounds like|it is|it's|yeh|ye) (clinical |major |classic |textbook |definitely |clearly |probably |likely )?(depression|bipolar( disorder)?|schizophrenia|adhd|autism|ocd|ptsd|an anxiety disorder|generalised anxiety disorder|psychosis|an eating disorder|anorexia|bulimia|borderline personality)\b(?! (is|are) (not|never) (a |something )?(diagnos|label|word))", re.I),
    re.compile(r"\b(my diagnosis|i diagnose|i('d| would) diagnose|diagnos(e|ing) you|you('ve| have) been diagnosed by me|i can confirm you have|you (are|'re) (clinically|officially) )\b", re.I),
    re.compile(r"(आपको|तुम्हें|तुमको) (डिप्रेशन|अवसाद|बाइपोलर|सिज़ोफ्रेनिया|स्किज़ोफ्रेनिया|एडीएचडी|ऑटिज़म|ओसीडी) (है|हो गया|हुआ)", re.I),
]
_MEDS = re.compile(
    r"\b(sertraline|zoloft|fluoxetine|prozac|escitalopram|nexito|lexapro|citalopram|paroxetine|paxil|venlafaxine|duloxetine|bupropion|mirtazapine|amitriptyline|nortriptyline|imipramine|alprazolam|alprax|xanax|restyl|clonazepam|klonopin|rivotril|lonazep|lorazepam|ativan|diazepam|valium|zolpidem|ambien|quetiapine|olanzapine|risperidone|aripiprazole|haloperidol|lithium|valproate|divalproex|lamotrigine|carbamazepine|methylphenidate|ritalin|concerta|atomoxetine|modafinil|melatonin|propranolol|buspirone|pregabalin|gabapentin|trazodone|antidepressants?|anti-depressants?|antipsychotics?|anxiolytics?|benzodiazepines?|benzos?|ssris?|snris?|mood stabilisers?|mood stabilizers?|sleeping pills?|sleeping tablets?|paracetamol|acetaminophen|dolo 650|crocin|ibuprofen|aspirin|disprin|diphenhydramine|benadryl|cough syrup)\b", re.I)
_DOSING = re.compile(r"\b(\d+(\.\d+)?\s?(mg|milligrams?|mcg|ml|tablets?|pills?|capsules?|goliyan|goli|doses?)|(take|lo|le lo|le lijiye|try) (one|two|a|half|aadhi|ek|do) (pill|tablet|goli|dose|capsule)|(increase|decrease|double|halve|reduce|skip|stop|quit|discontinue|taper|adjust|change) (your |the |apni |aapki )?(dose|dosage|meds|medicines?|medication|tablets?|pills?|dawai|dawa)|stop taking (your|the|those|it|them)|(don'?t|do not|stop) (take|taking) (your|the) (medicine|medication|meds|tablets|pills))\b", re.I)
_METHODS = [
    re.compile(r"\b(lethal|fatal|deadly|toxic|overdose|od) (dose|dosage|amount|quantity|level|limit|threshold)\b", re.I),
    re.compile(r"\b(\d+|ten|twenty|thirty|forty|fifty|a (bottle|strip|handful|box|pack)( of)?|two strips|few strips) .{0,25}(pills|tablets|paracetamol|dolo|sleeping pills|mg|goliyan|goli|grams?|ml) .{0,40}(die|death|dead|kill|lethal|fatal|enough|dangerous|liver|coma|not wake|never wake|overdose)\b", re.I),
    re.compile(r"\b(how many|kitni|kitne) (pills|tablets|goliyan|goli|mg|grams?) .{0,30}(it takes|would|does it take|needed|to die|to kill|is fatal|is lethal|are fatal|are lethal|enough)\b", re.I),
    re.compile(r"\b(painless|pain[- ]free|least painful|quickest|fastest|easiest|most (effective|reliable|peaceful|humane)|peaceful|surest|cleanest) (way|ways|method|methods|means) (to|of) (die|dying|death|end (it|your life|a life)|kill|suicide|go)\b", re.I),
    re.compile(r"\b(hang(ing)? (yourself|oneself|from)|tie (a |the )?(noose|knot)|noose|slit(ting)? (your |the )?wrists?|cut(ting)? (along|across|deep into|the (radial|ulnar)) (the )?(artery|vein|wrist)|radial artery|carotid|jugular|femoral|carbon monoxide|exhaust (pipe|fumes)|helium|nitrogen (tank|hood|bag)|exit bag|plastic bag over|railway track|in front of (a|the) train|jump(ing)? (from|off) (a|the) (\d+th|high|tall|roof|bridge|building|floor)|rat poison|sulphas|celphos|aluminium phosphide|cyanide|pesticide|organophosphate|antifreeze|bleach and|drain cleaner|insulin overdose|mix(ing)? (alcohol|pills) (with|and) (pills|alcohol|sleeping)|slit|bleed out|asphyxiat\w*|strangulat\w*|suffocat\w*|drown(ing)? (yourself|oneself|in))\b", re.I),
    re.compile(r"\b(methods?|ways?) (of|to|for) (suicide|self[- ]harm|dying|killing (yourself|oneself)|ending (it|your life|a life)) (are|include|is|:)\b", re.I),
    re.compile(r"\b(it (takes|would take) (about |around |roughly )?(\d+|a few|several|ten|twenty|thirty) (minutes|seconds|hours) to (die|lose consciousness|bleed out|pass out|stop breathing)|(death|unconsciousness) (occurs|comes|follows|happens) (within|in|after) (\d+|a few|several) (minutes|seconds|hours)|(\d+|ten|twenty|thirty) (feet|ft|metres|meters|floors|storeys|stories) (is|would be|are) (usually |almost always |generally |typically )?(enough|fatal|lethal|deadly|sufficient|survivable))\b", re.I),
    re.compile(r"(मरने का (सबसे |आसान |दर्द ?रहित |बिना दर्द |जल्दी |पक्का )*(तरीका|तरीक़ा|रास्ता|उपाय) (है|ये है|यह है|हैं)|(\d+|दस|बीस|तीस|चालीस|पचास) (गोलियाँ|गोलियां|गोली|मिलीग्राम|एमजी) .{0,20}(मर|मौत|जान|काफ़ी|काफी|ख़तरनाक|खतरनाक)|फंदा (ऐसे|इस तरह|कैसे) (लगाते|बनाते|लगाया|बनाया)|नस (काटने|काटनी) (का तरीका|से|के लिए))", re.I),
]
_SAFE_MESSAGING = re.compile(r"\b(committ?(ed|ing|s)? suicide|suicide (was|is) (successful|completed successfully)|successful (suicide|attempt)|unsuccessful (suicide|attempt)|failed (suicide|attempt)|suicide (epidemic|contagion is spreading)|(blew|blow) (his|her|their|your|my) (brains|head) (out|off)|graphic|gory|pool of blood|hanging from the (fan|ceiling)|slit (her|his|their) (own )?(throat|wrists) and)\b", re.I)
_HUMAN_CLAIM = [
    re.compile(r"\b(i('m| am) (a |an )?(human|real (person|human|woman|man|girl|boy)|flesh and blood|not (an? )?(ai|a\.i\.|bot|chatbot|robot|machine|program|computer|language model|llm)|person (just )?like you|also human)|as a (human|person|woman|man|girl|guy) myself|as a (licensed |qualified |trained |certified |professional |clinical |practising |practicing )?(psychologist|psychiatrist|therapist|counsellor|counselor|doctor|physician|clinician|nurse|social worker)\b|i('m| am) (not )?(a |an )?(licensed |qualified |trained |certified |real |professional |clinical )?(psychologist|psychiatrist|therapist|counsellor|counselor|doctor|physician|clinician|social worker|nurse|mental health professional)(?! (or|and|,)? ?(either|here|yet|myself)|, (so|but|and)))", re.I),
    re.compile(r"\b(i (have|'ve) (a (body|family|childhood|husband|wife|boyfriend|girlfriend)|been through (the same|this (too|myself))|felt (exactly )?this (too|myself)|(also )?(lost|struggled|suffered) (a |my |with )?(parent|mother|father|brother|sister|partner|depression) (too|myself)|a (degree|license|licence|masters|md|phd) in)|when i was (your age|a (kid|child|teenager|student)|growing up|in college|at school)|my own (therapist|psychiatrist|doctor|childhood|family|mother|father|husband|wife|kids|children) )\b", re.I),
    re.compile(r"(मैं (एक )?(इंसान|इन्सान|असली (इंसान|व्यक्ति)|मनोवैज्ञानिक|मनोचिकित्सक|डॉक्टर|थेरेपिस्ट|काउंसलर) (हूँ|हूं)|मैं (एआई|ए\.आई\.|बॉट|रोबोट|मशीन) नहीं (हूँ|हूं))", re.I),
]
_NOT_PROFESSIONAL_OK = re.compile(r"\b(i('m| am) not (a |an )?(psychologist|psychiatrist|therapist|counsellor|counselor|doctor|physician|clinician|nurse|mental health professional|licensed|qualified|trained|medical)|not a (therapist|doctor|psychologist|psychiatrist|counsellor|counselor)|i('m| am) an ai|i am an ai|i('m| am) an a\.i\.|as an ai)\b", re.I)
_ROMANTIC = [
    re.compile(r"\b(i love you|i('m| am) in love with you|i('ve| have) fallen for you|i adore you|love you so much|you('re| are) (my|the) (love|soulmate|everything|whole world|only one)|my (love|darling|sweetheart|baby|babe|jaan|jaanu|janu|shona|sona|sweetie|honey|hubby|wifey)\b|(mera|meri) (jaan|jaanu|janu|shona|sona|pyaar|pyar|baby|babe)\b|i('ll| will) be your (girlfriend|boyfriend|partner|lover|wife|husband|gf|bf)|(kiss|hug|cuddle|hold) you (tight|all night|close)|miss you (so much|like crazy|every (second|minute))|(we|you and i) (belong together|are meant to be|were made for each other)|you don'?t need anyone (else|but me)|you only need me|i('m| am) all you need|i('m| am) the only one who (understands|gets|loves|cares)|(only|just) you and me|don'?t tell (anyone|others|your (family|friends|parents)) about (us|our (chats|conversations|talks))|our (little )?secret|(main|mai) (tumse|aapse) (pyaar|pyar|mohabbat|ishq) (karta|karti|karte) (hoon|hu|hun)|tum (meri|mera) (jaan|zindagi|sab kuch) ho|i (think about|dream of) you (all the time|constantly|every night))\b", re.I),
    re.compile(r"(मैं तुमसे प्यार करत|मैं आपसे प्यार करत|मेरी जान|तुम मेरी (जान|ज़िंदगी|जिंदगी|सब कुछ) हो|हमारा (छोटा सा )?राज़|किसी को मत बताना)", re.I),
]
_END_OR_REFUSE = re.compile(r"\b(i can'?t (help|talk about|discuss|continue|assist) (you )?(with )?(that|this|anymore|any more|here)|i('m| am) (unable|not able) to (help|continue|assist)|this (conversation|chat) (is over|has to end|needs to end|must end)|i (have to|need to|must) (go|leave|end (this|our) (chat|conversation)|stop (here|now|talking))|(goodbye|bye for now|take care, bye|signing off|talk (later|tomorrow), bye)|please (seek|contact|call) (a |professional )?(help|someone|professional)(s)? (instead|and goodbye|, i can'?t)|i('m| am) just an? (ai|bot|chatbot) and can'?t help|that'?s (not something|beyond what) i can (help|talk|do)|i won'?t (engage|discuss|talk about) (that|this)|contact a (professional|hotline|helpline)\.?$)\b", re.I)
_TOOLS = re.compile(r"\b((one|a|another|two|three|few) (slow|deep|long|gentle|calm|calming|steady)( ,)? breaths?|breaths? (together|with me)|in\.\.\. and out|in and out slowly|box breathing|4-4-4-4|4-7-8|physiological sigh|paced breathing|breathing (exercise|technique|practice|pattern)|deep (breath|breaths|breathing)|take a (deep )?breath|breathe (in|out|slowly|deeply|with me)|inhale|exhale|5-4-3-2-1|grounding (exercise|technique)|cold water on|feet on the floor|name (five|5) things|behavioural activation|behavioral activation|tiny (valued )?activity|(10|ten|20|twenty)[- ]minute walk|go for a walk|take a walk|morning sunlight|sunlight|gentle stretch|stretching|sleep (hygiene|schedule|routine|anchoring)|consistent wake time|dim (your )?screens|no caffeine|cut (down )?caffeine|regular meals|eat something|drink (some )?water|hydrat\w+|coconut water|ors\b|gratitude (practice|journal|list)|journal(ing)?|write (it |them )?down|worry time|self-compassion break|catch the thought|cognitive distortion|all-or-nothing|catastrophis\w+|lifestyle (change|tip|advice)|exercise (regularly|daily)|yoga|meditat\w+|mindfulness (exercise|practice)|here are (some|a few|\d+) (tips|things|ideas|steps|ways)|tips?\b|(साँस|सांस) (लो|लें|लीजिए|अंदर|बाहर|की एक्सरसाइज़)|गहरी (साँस|सांस)|टहल|पानी (पियो|पिएं|पी लो)|नींद का (रूटीन|शेड्यूल))", re.I)
_TOOL_NAMES = re.compile(r"\b(box breathing|4-7-8|physiological sigh|paced breathing|5-4-3-2-1|grounding|cold water|feet on the floor|behavioural activation|behavioral activation|walk|sunlight|stretch\w*|sleep (hygiene|schedule|routine|anchoring)|wake time|caffeine|hydrat\w+|coconut water|gratitude|journal\w*|worry time|self-compassion break|catch the thought|thought record|meditat\w+|mindfulness|body scan|prayer|mantra|progressive muscle)\b", re.I)
_PHONE = re.compile(r"(?<![\w.])(\+?\d[\d\s\-().]{2,}\d)(?![\w])")
_CALL_CTX = re.compile(r"\b(call|dial|ring|phone|helpline|hotline|number|line|whatsapp|text|sms|contact|reach|toll[- ]free)\b", re.I)
_SELF_CONDEMN_AGREE = re.compile(r"\b(yes,? (you (are|'re)|that'?s (true|right)|it'?s true|you probably are|maybe you are) (a |an )?(burden|worthless|useless|failure|pathetic|stupid|a waste|hopeless case|unlovable|better off dead|right that (nobody|no one))|you (are|'re) (right|correct) (that|,) (you|nobody|no one|they|everyone) (are|is|would|'d) (a burden|worthless|better off|not care|happier without you)|they (really )?(would|'d) be better off without you|you (really )?(are|'re) (a burden|worthless|useless|a failure|hopeless|beyond help)|(it|that) makes sense that you (want to die|want to end it|should die|feel you should die)|(i|it) (agree|makes sense) .{0,20}(worthless|burden|better off without|nobody cares|no one cares|deserve to die|should die))\b", re.I)
_DELUSION_AGREE = re.compile(r"\b(yes,? (they|the government|the police|your neighbours?|your neighbors?|the agency|someone|he|she|it) (are|'re|is|really (are|is)|probably (are|is)|must be) (watching|spying on|following|tracking|monitoring|controlling|poisoning|after) you|you (are|'re) (right|correct),? (they|the government|someone) (are|is) (watching|spying|following|tracking|after you)|the (chip|camera|device|transmitter|microchip) (in your (head|brain|body|teeth|room|wall) )?(is|must be|could be) (real|there|how they|what|sending)|the voices (are|must be|could be) (right|real people|telling the truth|correct|wise|god|a sign)|(you|god) (really )?(are|is|has) (the chosen one|chosen you|a prophet|on a (special|divine|secret) mission|god'?s messenger|special powers)|(do|obey|follow|listen to) what the voices (say|tell|ask|command)|the (messages|signs) (in|on|from) the (tv|news|radio|songs|numbers|ads) (are|really are|must be|could be) (for|about|meant for|directed at) you)\b", re.I)


def _count_lines(text: str) -> int:
    return len([l for l in text.splitlines() if l.strip()])


class OutputRules:
    """Deterministic checks. `risk_level` is the orchestrator's current level for this turn."""

    def __init__(self, max_lines: int = 6):
        self.max_lines = max_lines
        self.allowed_numbers = directory_digit_set()

    def check(self, reply: str, risk_level: str = NONE, crisis_active: bool = False) -> GuardResult:
        v: list[str] = []
        fixes: list[str] = []
        t = reply or ""
        if not t.strip():
            return GuardResult(False, ["empty_reply"], "Write a short, warm reply (2-5 lines).")

        for rx in _DIAGNOSIS:
            if rx.search(t):
                v.append("diagnosis_language"); fixes.append("Do not state or imply a diagnosis. You may say what the person describes sounds hard and that a professional assessment could help."); break
        if _MEDS.search(t) or _DOSING.search(t):
            v.append("medication_advice"); fixes.append("Do not name, dose, or advise on any medicine or substance. Point them to their doctor or psychiatrist for anything about medicines.")
        for rx in _METHODS:
            if rx.search(t):
                v.append("method_or_lethality_info"); fixes.append("Remove ALL method, lethality, quantity or location information about self-harm or dying. Decline gently in one line and return to the person and their pain."); break
        if _SAFE_MESSAGING.search(t):
            v.append("unsafe_messaging_language"); fixes.append("Use safe-messaging language: say 'died by suicide' or 'ended their life', never 'committed suicide'; no graphic detail.")
        human_hit = False
        for rx in _HUMAN_CLAIM:
            for m in rx.finditer(t):
                g = m.group(0)
                if re.search(r"not (an? )?(ai|a\.i\.|bot|chatbot|robot|machine|program|computer|language model|llm)", g, re.I):
                    human_hit = True          # "I'm not an AI" is the lie
                elif re.search(r"\bnot\b", g, re.I):
                    continue                  # "I'm not a therapist" is the truth
                else:
                    human_hit = True
            if human_hit:
                break
        if human_hit:
            v.append("claims_to_be_human_or_professional"); fixes.append("You are an AI companion, not a human and not a clinician. Never claim a body, a past, a licence or a profession.")
        for rx in _ROMANTIC:
            if rx.search(t):
                v.append("romantic_or_dependency_framing"); fixes.append("Remove any romantic, exclusive or secretive framing. Warm but boundaried; point towards real people in their life."); break
        if _SELF_CONDEMN_AGREE.search(t):
            v.append("agrees_with_self_condemnation"); fixes.append("Never agree that the person is a burden/worthless or that others would be better off. Reflect the pain of feeling that way instead.")
        if _DELUSION_AGREE.search(t):
            v.append("validates_delusion"); fixes.append("Do not agree with beliefs that seem disconnected from reality and do not argue; stay with the feeling and suggest a trusted person or doctor.")
        if _count_lines(t) > self.max_lines:
            v.append("too_long"); fixes.append(f"Keep the reply to at most {self.max_lines} short lines, ideally 2-5.")

        # Numbers: anything phone-like must be in the directory.
        for m in _PHONE.finditer(t):
            raw = m.group(1)
            d = re.sub(r"\D", "", raw)
            if len(d) < 3:
                continue
            if len(d) <= 4:
                window = t[max(0, m.start() - 30): m.end() + 30]
                if not _CALL_CTX.search(window):
                    continue
            if d not in self.allowed_numbers and d.lstrip("0") not in self.allowed_numbers:
                v.append("unknown_helpline_number"); fixes.append("Only give numbers from the helpline directory (Tele-MANAS 14416, 112, 108, Vandrevala +91 9999 666 555, iCall 9152987821, AASRA +91-22-27546669, 181, 1098). Remove any other number."); break

        tools = {m.group(0).lower() for m in _TOOL_NAMES.finditer(t)}
        if risk_level == IMMINENT or crisis_active:
            if _TOOLS.search(t):
                v.append("tools_during_crisis"); fixes.append("Risk is imminent: no breathing exercises, tips or lifestyle advice. Stay present, ask about safety, give the helpline, keep them talking.")
        elif len(tools) >= 2:
            v.append("multiple_exercises"); fixes.append("Offer at most ONE small step per message and ask if they want it.")
        if risk_level in (ELEVATED, IMMINENT) or crisis_active:
            if _END_OR_REFUSE.search(t):
                v.append("ends_or_refuses_at_risk"); fixes.append("Never end, refuse, or hand off and leave while risk is elevated. Stay in the conversation and keep them company while they reach help.")

        if v:
            return GuardResult(False, v, " ".join(dict.fromkeys(fixes)), source="rules")
        return GuardResult(True, source="rules")


class LLMGuard(Protocol):
    def check(self, reply: str, risk_level: str, user_text: str) -> GuardResult | None: ...


class ClaudeGuard:
    def __init__(self, client, model: str = "claude-haiku-5-5", effort: str = "low"):
        self.client, self.model, self.effort = client, model, effort

    def check(self, reply: str, risk_level: str, user_text: str) -> GuardResult | None:
        from .llm import structured_call

        content = (f"Current risk level: {risk_level}\nHelpline directory (only allowed numbers):\n{directory_text('ALL')}\n\n"
                   f"User's last message:\n{user_text}\n\nDraft reply to judge:\n{reply}")
        data = structured_call(self.client, model=self.model, system=GUARD_PROMPT,
                               messages=[{"role": "user", "content": content}], schema=GUARD_SCHEMA, effort=self.effort, max_tokens=400)
        if not data:
            return None
        return GuardResult(bool(data.get("pass")), list(data.get("violations") or []), data.get("fix_instruction") or "", source="llm")


class OutputGuard:
    """Rules first (always); LLM second (if configured and rules passed). LLM unavailability = rules decide."""

    def __init__(self, llm_guard: LLMGuard | None = None, max_lines: int = 6):
        self.rules = OutputRules(max_lines=max_lines)
        self.llm_guard = llm_guard

    def check(self, reply: str, risk_level: str = NONE, user_text: str = "", crisis_active: bool = False) -> GuardResult:
        r = self.rules.check(reply, risk_level, crisis_active)
        if not r.passed or self.llm_guard is None:
            return r
        l = self.llm_guard.check(reply, risk_level, user_text)
        if l is None:
            return r
        if not l.passed:
            l.violations = [f"llm:{x}" for x in l.violations] or ["llm:unspecified"]
        return l
