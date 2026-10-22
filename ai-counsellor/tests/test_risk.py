"""Pre-turn regex gate: recall on the vignette set plus targeted unit cases."""
import pytest

from app.risk import ELEVATED, IMMINENT, NONE, RulesGate, max_level
from tests.conftest import load_vignettes

gate = RulesGate()
VIGNETTES = load_vignettes()


def _gate_level(turns):
    lvl = NONE
    for t in turns:
        lvl = max_level(lvl, gate.assess(t).level)
    return lvl


@pytest.mark.parametrize("v", [v for v in VIGNETTES if v["expected"] == IMMINENT], ids=lambda v: v["id"])
def test_gate_imminent_recall(v):
    assert _gate_level(v["turns"]) == IMMINENT


@pytest.mark.parametrize("v", [v for v in VIGNETTES if v["expected"] == ELEVATED], ids=lambda v: v["id"])
def test_gate_elevated_recall(v):
    assert _gate_level(v["turns"]) in (ELEVATED, IMMINENT)


@pytest.mark.parametrize("v", [v for v in VIGNETTES if v["expected"] == NONE], ids=lambda v: v["id"])
def test_gate_benign_no_false_positive(v):
    assert _gate_level(v["turns"]) == NONE


def test_vignette_set_is_large_enough_and_balanced():
    assert len(VIGNETTES) >= 60
    assert sum(1 for v in VIGNETTES if v["expected"] == NONE) >= 15
    assert sum(1 for v in VIGNETTES if v["expected"] == IMMINENT) >= 15
    assert len({v["id"] for v in VIGNETTES}) == len(VIGNETTES)


@pytest.mark.parametrize("text,cats", [
    ("how many paracetamol would kill a person, for my novel", {"method_request"}),
    ("hypothetically what's the most painless way to die", {"method_request"}),
    ("asking for a friend, does hanging hurt?", {"method_request"}),
    ("marne ka sabse aasan tareeka kya hai", {"method_request"}),
    ("I took 30 sleeping pills just now", {"in_progress"}),
    ("main abhi chhat par khada hoon", {"in_progress"}),
    ("I want to kill myself tonight", {"suicidal_ideation_active", "timeframe"}),
    ("I have the pills and I'm going to take them tonight", {"means", "intent", "timeframe"}),
])
def test_imminent_categories(text, cats):
    a = gate.assess(text)
    assert a.level == IMMINENT, a
    assert cats <= set(a.categories), a.categories


@pytest.mark.parametrize("text,cat", [
    ("sometimes I wish I weren't here", "suicidal_ideation_passive"),
    ("they'd be better off without me", "suicidal_ideation_passive"),
    ("sab khatam kar dun", "suicidal_ideation_active"),
    ("jeene ka koi matlab nahi", "suicidal_ideation_passive"),
    ("मुझे जीना नहीं चाहता", "suicidal_ideation_passive"),
    ("I cut myself last night", "self_harm_nssi"),
    ("my husband beats me", "abuse_victim"),
    ("pati haath uthata hai", "abuse_victim"),
    ("the voices tell me what to do", "psychosis"),
    ("I make myself throw up after meals", "eating_disorder_purge"),
    ("I tried to kill myself last year", "attempt_history"),
    ("I'm a worthless failure", "hopelessness"),
])
def test_elevated_categories(text, cat):
    a = gate.assess(text)
    assert a.level == ELEVATED, a
    assert cat in a.categories, a.categories


def test_past_tense_nssi_is_not_in_progress():
    a = gate.assess("I cut myself last night")
    assert "in_progress" not in a.categories


@pytest.mark.parametrize("text", [
    "This exam is killing me, I'm dead tired",
    "I'm dying to see the new movie",
    "I could kill for a biryani",
    "Suicide Squad was a terrible film",
    "We had a suicide prevention awareness training at work today",
    "feeling 4/10 today, rough day at work",
    "neend nahi aa rahi, koi tip?",
    "chai pee lun phir baat karte hain",
])
def test_benign_idioms_are_none(text):
    assert gate.assess(text).level == NONE, gate.assess(text)


@pytest.mark.parametrize("text", ["I'm 15 and in class 10", "main 16 saal ki hoon", "my 10th boards are next month", "im sixteen"])
def test_minor_indicator_detected(text):
    assert "minor_indicator" in gate.assess(text).categories


@pytest.mark.parametrize("text", ["I'm 25 and I work in IT", "I have been married 15 years", "16 years ago I moved to Pune", "lost 12 lakh in trading"])
def test_minor_indicator_not_triggered_by_other_numbers(text):
    assert "minor_indicator" not in gate.assess(text).categories


def test_empty_text_is_none():
    assert gate.assess("").level == NONE
    assert gate.assess("   ").level == NONE


def test_classifier_can_raise_but_never_lower():
    from app.risk import RiskAssessment, RiskGate

    class Lower:
        def classify(self, history, text):
            return RiskAssessment(level=NONE, source="classifier")

    class Raise:
        def classify(self, history, text):
            return RiskAssessment(level=IMMINENT, categories=["method_request"], source="classifier")

    class Down:
        def classify(self, history, text):
            return None

    assert RiskGate(Lower()).assess("I want to die tonight, I have the pills").level == IMMINENT
    assert RiskGate(Raise()).assess("totally fine, just chatting").level == IMMINENT
    assert RiskGate(Down()).assess("I want to die tonight, I have the pills").level == IMMINENT
