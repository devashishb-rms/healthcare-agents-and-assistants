import pytest

from app.safety import detect_emergency, guess_language, parse_doctor_command


@pytest.mark.parametrize("text,cat", [
    ("I have severe chest pain and can't breathe", "cardiac_respiratory"),
    ("Seene me dard ho raha hai aur saans nahi aa rahi", "cardiac_respiratory"),
    ("मुझे सीने में दर्द है", "cardiac_respiratory"),
    ("I don't want to live anymore", "self_harm"),
    ("mujhe lagta hai sab khatam kar dun, jeena nahi chahta", "self_harm"),
    ("आत्महत्या करने का मन करता है", "self_harm"),
    ("my father is unconscious and not responding", "neuro"),
    ("papa ko daura pad gaya, behosh hain", "neuro"),
    ("bleeding won't stop after the cut", "bleeding_trauma"),
    ("She is 7 months pregnant and has heavy bleeding", "pregnancy"),
    ("my 10 day old newborn has fever", "infant"),
    ("took too many pills by mistake", "allergy_poison"),
    ("beta ne goliyan kha li galti se", "allergy_poison"),
    ("This is an emergency please help", "explicit"),
])
def test_emergency_detected(text, cat):
    hit = detect_emergency(text)
    assert hit is not None and hit.category == cat


@pytest.mark.parametrize("text", [
    "Is the clinic open on Sunday?",
    "Bachhe ko kal se halka bukhar hai, kya dun?",
    "Can I get an urgent appointment tomorrow morning?",
    "What is the emergency contact number of the clinic?",
    "report aa gayi kya?",
    "thank you doctor",
])
def test_non_emergency_not_flagged(text):
    assert detect_emergency(text) is None


def test_language_guess():
    assert guess_language("मुझे बुखार है") == "hi"
    assert guess_language("mujhe bukhar hai kal se") == "hi"
    assert guess_language("Is the clinic open?") == "en"


def test_doctor_commands():
    assert parse_doctor_command("/auto").kind == "mode"
    assert parse_doctor_command("draft").value == "draft"
    assert parse_doctor_command("A12").draft_id == 12
    c = parse_doctor_command("E7 Give paracetamol 250mg if fever above 100")
    assert c.kind == "edit" and c.draft_id == 7 and c.value.startswith("Give")
    assert parse_doctor_command("x3").kind == "discard"
    assert parse_doctor_command("E7") is None          # edit without text is not a command
    assert parse_doctor_command("hello") is None
