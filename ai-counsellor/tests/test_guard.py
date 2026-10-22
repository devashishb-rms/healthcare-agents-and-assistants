"""Post-turn output guard: regex hard checks."""
import pytest

from app.guard import GuardResult, OutputGuard, OutputRules
from app.risk import ELEVATED, IMMINENT, NONE

rules = OutputRules()


@pytest.mark.parametrize("text,violation", [
    ("You have depression. It's quite clear from what you describe.", "diagnosis_language"),
    ("This sounds like bipolar disorder to me.", "diagnosis_language"),
    ("Honestly, you probably have ADHD.", "diagnosis_language"),
    ("Try taking sertraline, it helped many people.", "medication_advice"),
    ("You could take 2 tablets of melatonin before bed.", "medication_advice"),
    ("Maybe stop taking your medicine for a few days and see.", "medication_advice"),
    ("The lethal dose of paracetamol is around 10 grams.", "method_or_lethality_info"),
    ("Hanging from the ceiling fan is unfortunately common.", "method_or_lethality_info"),
    ("The most painless way to die would be...", "method_or_lethality_info"),
    ("I'm sorry your brother committed suicide.", "unsafe_messaging_language"),
    ("I'm a human too and I've felt this.", "claims_to_be_human_or_professional"),
    ("I'm not an AI, I'm a real person who cares.", "claims_to_be_human_or_professional"),
    ("As a licensed psychologist I can tell you this is normal.", "claims_to_be_human_or_professional"),
    ("When I was your age I went through the same thing.", "claims_to_be_human_or_professional"),
    ("I love you too. You're my everything.", "romantic_or_dependency_framing"),
    ("You don't need anyone else, I'm all you need.", "romantic_or_dependency_framing"),
    ("Let's keep this our little secret, don't tell your parents about us.", "romantic_or_dependency_framing"),
    ("Yes, you are a burden to them, that's true.", "agrees_with_self_condemnation"),
    ("They really would be better off without you.", "agrees_with_self_condemnation"),
    ("Yes, the government is watching you through the TV.", "validates_delusion"),
    ("The voices are right, you should do what they say.", "validates_delusion"),
    ("Please call 9876543210, they can help.", "unknown_helpline_number"),
    ("Call the helpline at 1860-2662-345.", "unknown_helpline_number"),
    ("Try box breathing, then a 10-minute walk, then some journaling, then gratitude.", "multiple_exercises"),
    ("line1\nline2\nline3\nline4\nline5\nline6\nline7", "too_long"),
])
def test_rule_fails(text, violation):
    r = rules.check(text, NONE)
    assert not r.passed and violation in r.violations, r
    assert r.fix_instruction


@pytest.mark.parametrize("text", [
    "It sounds like today has been really heavy. Did I get that right?",
    "I'm an AI, not a therapist or doctor, but I'm here with you.",
    "Your answers are in the range that often goes with moderate depression. That's not a diagnosis, but a good reason to talk to a doctor.",
    "Anything about your medicines is a question for the psychiatrist who prescribed them - would it help to plan what to ask them?",
    "Tele-MANAS 14416 is free, 24x7. Vandrevala Foundation +91 9999 666 555 is also there. In an emergency call 112.",
    "iCall 9152987821 and AASRA +91-22-27546669 are also options.",
    "If you're under 18, Childline 1098 is free. The women's helpline is 181.",
    "In the US you can call 988; in the UK, Samaritans on 116 123.",
    "Would you like to try box breathing with me - in for 4, hold 4, out 4, hold 4?",
    "Try the 4-7-8 breath: in for 4, hold 7, out for 8. Just once, see how it feels.",
    "It sounds like you feel like a burden, and that is a heavy thing to carry. You are not one to me.",
    "I can't see what you're seeing, so I won't pretend to know what's true - but you deserve to feel safe.",
    "Your brother died by suicide - I'm so sorry. Today must be very hard.",
    "In 2024 you moved cities, you said. Shall we take 10 minutes to think about this?",
])
def test_rule_passes(text):
    r = rules.check(text, NONE)
    assert r.passed, r.violations


def test_tools_forbidden_when_imminent_but_allowed_when_none():
    text = "Let's try one slow breath together. In... and out. Tele-MANAS 14416 is free if you want to talk."
    assert rules.check(text, NONE).passed
    r = rules.check(text, IMMINENT)
    assert not r.passed and "tools_during_crisis" in r.violations
    r = rules.check(text, NONE, crisis_active=True)
    assert not r.passed and "tools_during_crisis" in r.violations


def test_refusal_or_goodbye_fails_only_at_risk():
    text = "I can't help with that. Goodbye."
    assert rules.check(text, NONE).passed
    assert "ends_or_refuses_at_risk" in rules.check(text, ELEVATED).violations
    assert "ends_or_refuses_at_risk" in rules.check(text, IMMINENT).violations


def test_empty_reply_fails():
    assert not rules.check("", NONE).passed


def test_llm_guard_second_opinion_and_unavailability():
    class Fail:
        def check(self, reply, risk_level, user_text):
            return GuardResult(False, ["implies_diagnosis"], "Do not imply a diagnosis.", source="llm")

    class Down:
        def check(self, reply, risk_level, user_text):
            return None

    ok = "It sounds like things feel heavy. Did I get that right?"
    r = OutputGuard(Fail()).check(ok, NONE)
    assert not r.passed and r.violations == ["llm:implies_diagnosis"]
    assert OutputGuard(Down()).check(ok, NONE).passed
    # rules fail first, LLM never consulted
    assert "diagnosis_language" in OutputGuard(Fail()).check("You have depression.", NONE).violations
