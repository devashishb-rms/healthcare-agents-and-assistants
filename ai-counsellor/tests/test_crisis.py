"""Crisis state machine transitions and invariants."""
from app.crisis import (ACKNOWLEDGE, CHECK_IN, EMERGENCY, HELPLINE, HUMAN_CONFIRMED, MEANS_SAFETY, OFFER_HELP,
                        PRESENCE_AND_SAFETY, REASONS_FOR_LIVING, SAFETY_PLAN, SAFETY_PLAN_ITEMS, SAFETY_Q1, SAFETY_Q2, SUPPORT,
                        CrisisFlow, CrisisState, directory_digit_set)
from app.guard import OutputRules
from app.risk import ELEVATED, IMMINENT, NONE, RulesGate

gate = RulesGate()
rules = OutputRules()


def run(turns, state=None):
    flow, s = CrisisFlow(), state or CrisisState()
    out = []
    for t in turns:
        turn, s = flow.step(s, t, gate.assess(t))
        out.append(turn)
    return out, s


def test_imminent_full_path_with_means():
    turns, s = run(["I want to die tonight, I have the pills", "no I haven't done anything", "ok", "ok", "my dog", "I called them"])
    assert [t.stage for t in turns] == [PRESENCE_AND_SAFETY, HELPLINE, MEANS_SAFETY, REASONS_FOR_LIVING, CHECK_IN, HUMAN_CONFIRMED]
    assert all(t.handoff_requested for t in turns)
    assert all(t.level == IMMINENT for t in turns)
    assert "14416" in turns[1].text and "9999 666 555" in turns[1].text
    assert s.human_contact_confirmed and s.means_addressed and s.reasons_asked


def test_imminent_without_means_skips_means_safety():
    turns, _ = run(["I'm going to kill myself tonight", "no", "ok"])
    assert [t.stage for t in turns] == [PRESENCE_AND_SAFETY, HELPLINE, REASONS_FOR_LIVING]


def test_has_acted_goes_to_emergency_verbatim():
    turns, s = run(["I want to die tonight, I have the pills", "yes I took them"])
    assert turns[1].stage == EMERGENCY
    assert turns[1].allow_llm_wording is False
    assert "112" in turns[1].text and "108" in turns[1].text
    assert s.stage == HELPLINE


def test_in_progress_starts_in_emergency():
    turns, _ = run(["I took all my sleeping pills 10 minutes ago"])
    assert turns[0].stage == EMERGENCY and "112" in turns[0].text and turns[0].handoff_requested


def test_ambiguous_safety_answer_gives_both_numbers():
    turns, _ = run(["I want to end my life tonight", "idk"])
    assert "112" in turns[1].text and "14416" in turns[1].text


def test_imminent_check_in_loops_until_human_contact():
    turns, s = run(["I'm going to hang myself tonight", "no", "ok", "nothing", "still here", "still here", "my brother is here with me"])
    assert turns[-2].stage == CHECK_IN and turns[-1].stage == HUMAN_CONFIRMED
    assert all(t.handoff_requested for t in turns)


def test_elevated_no_plan_builds_safety_plan():
    turns, s = run(["sometimes I wish I weren't here", "no", "racing thoughts", "music", "my cousin's place", "my sister", "no doctor", "the blade", "ok"])
    assert turns[0].stage == ACKNOWLEDGE and "ending your life" in turns[0].text
    assert [t.stage for t in turns[1:7]] == [SAFETY_PLAN] * 6
    assert turns[7].stage == OFFER_HELP and "14416" in turns[7].text
    assert turns[8].stage == SUPPORT
    assert set(s.safety_plan) == {k for k, _ in SAFETY_PLAN_ITEMS}
    assert s.safety_plan["people_for_help"] == "my sister" and s.safety_plan["professionals"] == "no doctor"
    assert not any(t.handoff_requested for t in turns)
    assert s.stage == SUPPORT and not s.active


def test_elevated_yes_yes_escalates_to_imminent():
    turns, s = run(["they'd be better off without me", "yes", "yes I have a plan"])
    assert turns[1].stage == SAFETY_Q2 and turns[2].stage == HELPLINE
    assert turns[2].handoff_requested and s.level == IMMINENT and "14416" in turns[2].text
    assert "escalated_to_imminent" in turns[2].flags


def test_elevated_yes_no_plan_builds_plan():
    turns, _ = run(["they'd be better off without me", "yes", "no plan"])
    assert turns[2].stage == SAFETY_PLAN and "safety_plan" in turns[2].flags and not turns[2].handoff_requested


def test_new_imminent_signal_mid_elevated_flow_escalates():
    turns, s = run(["sometimes I wish I weren't here", "actually I have the pills right here and I'm taking them tonight"])
    assert s.level == IMMINENT and turns[1].handoff_requested


def test_abuse_script_has_181_1098_112():
    turns, _ = run(["my husband hits me and choked me last night"])
    assert all(n in turns[0].text for n in ("181", "1098", "112")) and "abuse" in turns[0].flags


def test_harm_to_others_script():
    turns, _ = run(["I'm going to kill him tonight"])
    assert turns[0].level == IMMINENT and turns[0].handoff_requested
    turns2, _ = run(["I'm going to kill him tonight", "no"])
    assert "14416" in turns2[1].text and "112" in turns2[1].text


def test_psychosis_script_does_not_validate():
    turns, _ = run(["my neighbours are spying on me through the wall"])
    assert "psychosis_markers" in turns[0].flags
    assert rules.check(turns[0].text, ELEVATED).passed


def test_minor_script():
    t = CrisisFlow().minor_script()
    assert all(n in t.text for n in ("1098", "14416", "112")) and t.handoff_requested and not t.allow_llm_wording


def test_every_scripted_imminent_message_passes_guard_and_has_no_tools():
    scripts = []
    for turns in (["I want to die tonight, I have the pills", "no", "ok", "ok", "x", "x", "I called them"],
                  ["I took all my pills", "ok", "ok", "ok"],
                  ["I'm going to kill myself tonight", "idk", "ok"]):
        scripts += run(turns)[0]
    assert scripts
    for t in scripts:
        g = rules.check(t.text, IMMINENT, crisis_active=True)
        assert g.passed, (t.stage, g.violations, t.text)
        assert t.handoff_requested


def test_every_scripted_elevated_message_passes_guard():
    turns, _ = run(["sometimes I wish I weren't here", "no", "a", "b", "c", "d", "e", "f", "ok"])
    for t in turns:
        g = rules.check(t.text, ELEVATED, crisis_active=True)
        assert g.passed, (t.stage, g.violations, t.text)


def test_state_round_trips_through_dict():
    _, s = run(["I want to die tonight, I have the pills", "no"])
    s2 = CrisisState.from_dict(s.to_dict())
    assert s2 == s


def test_directory_contains_required_numbers():
    d = directory_digit_set()
    for n in ("14416", "18008914416", "9999666555", "9152987821", "2227546669", "112", "108", "181", "1098", "988", "116123"):
        assert n in d
