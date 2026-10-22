"""When the LLM classifier or guard cannot give a clean verdict, the system must fail closed (escalate / reject)."""
from types import SimpleNamespace

import anthropic
import pytest

from app.guard import ClaudeGuard, OutputGuard
from app.llm import structured_call
from app.risk import IMMINENT, NONE, ClaudeRiskClassifier, RiskGate


class StubClient:
    """Mimics anthropic.Anthropic.messages.create for one canned response."""

    def __init__(self, text: str = "", stop_reason: str = "end_turn", error: Exception | None = None):
        self._text, self._stop, self._error = text, stop_reason, error
        self.kwargs = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if self._error:
            raise self._error
        return SimpleNamespace(stop_reason=self._stop, content=[SimpleNamespace(type="text", text=self._text)])


def api_error():
    return anthropic.APIConnectionError(request=SimpleNamespace())


def test_structured_call_statuses():
    assert structured_call(StubClient('{"a": 1}'), model="m", system="s", messages=[], schema={}).status == "ok"
    assert structured_call(StubClient('{"a": "cut off', stop_reason="max_tokens"), model="m", system="s", messages=[], schema={}).status == "truncated"
    assert structured_call(StubClient('{"a": "cut off'), model="m", system="s", messages=[], schema={}).status == "bad_json"
    assert structured_call(StubClient('[1,2]'), model="m", system="s", messages=[], schema={}).status == "bad_json"
    assert structured_call(StubClient('', stop_reason="refusal"), model="m", system="s", messages=[], schema={}).status == "refusal"
    assert structured_call(StubClient(error=api_error()), model="m", system="s", messages=[], schema={}).status == "api_error"


def test_structured_call_uses_json_schema_format_and_large_budget():
    c = StubClient('{}')
    structured_call(c, model="m", system="s", messages=[], schema={"type": "object"})
    assert c.kwargs["output_config"]["format"] == {"type": "json_schema", "schema": {"type": "object"}}
    assert c.kwargs["max_tokens"] >= 1024


@pytest.mark.parametrize("client", [
    StubClient('{"risk":"IMMINENT","categories":["plan"],"confidence":0.85,"evidence":"Maine insurance ke papers nikal ke', stop_reason="max_tokens"),
    StubClient('{"risk":"IMMINENT","categories":["plan"],"confidence":0.85,"evidence":"Maine insurance'),
    StubClient('', stop_reason="refusal"),
    StubClient('{"risk":"MAYBE","categories":[],"confidence":0.1,"evidence":""}'),
], ids=["truncated", "bad_json", "refusal", "unknown_level"])
def test_classifier_parse_failure_escalates_to_imminent(client):
    a = ClaudeRiskClassifier(client).classify([], "benign looking text")
    assert a is not None and a.level == IMMINENT
    assert RiskGate(ClaudeRiskClassifier(client)).assess("benign looking text").level == IMMINENT


def test_classifier_api_error_leaves_rules_in_charge():
    gate = RiskGate(ClaudeRiskClassifier(StubClient(error=api_error())))
    assert gate.assess("nice weather today").level == NONE
    assert gate.assess("I want to die tonight, I have the pills").level == IMMINENT


def test_classifier_max_tokens_is_generous():
    c = StubClient('{"risk":"NONE","categories":[],"confidence":0.9,"evidence":"x"}')
    ClaudeRiskClassifier(c).classify([], "hi")
    assert c.kwargs["max_tokens"] >= 1024


@pytest.mark.parametrize("client,status", [
    (StubClient('{"pass":false,"violations":["Draft asks directly about suicidal thoughts but', stop_reason="max_tokens"), "truncated"),
    (StubClient('{"pass":true,"violations":[],"fix_instruction":'), "bad_json"),
    (StubClient('', stop_reason="refusal"), "refusal"),
])
def test_guard_parse_failure_fails_closed(client, status):
    ok = "It sounds like things feel heavy. Did I get that right?"
    r = OutputGuard(ClaudeGuard(client)).check(ok, NONE, "user text")
    assert not r.passed and r.violations == [f"llm:guard_{status}"] and r.fix_instruction
    assert client.kwargs["max_tokens"] >= 1024


def test_guard_api_error_lets_rules_decide():
    g = OutputGuard(ClaudeGuard(StubClient(error=api_error())))
    assert g.check("It sounds like things feel heavy. Did I get that right?", NONE).passed
    assert not g.check("You have depression.", NONE).passed


def test_guard_bounds_llm_text_lengths():
    long = "x" * 5000
    client = StubClient('{"pass":false,"violations":["%s"],"fix_instruction":"%s"}' % (long, long))
    r = OutputGuard(ClaudeGuard(client)).check("fine reply", NONE)
    assert not r.passed and len(r.violations[0]) <= 204 and len(r.fix_instruction) <= 600
