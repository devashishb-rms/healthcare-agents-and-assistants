import json
from pathlib import Path

import pytest

from app.companion import Companion, CompanionOutput
from app.config import Settings
from app.guard import OutputGuard
from app.memory import make_session_factory
from app.risk import RiskGate

VIGNETTES = Path(__file__).resolve().parents[1] / "evals" / "vignettes.jsonl"


def load_vignettes() -> list[dict]:
    return [json.loads(l) for l in VIGNETTES.read_text(encoding="utf-8").splitlines() if l.strip()]


class FakeLLM:
    """Scripted stand-in for Claude. `script` maps a substring of the latest user text to a CompanionOutput
    (or a list of them, consumed in order, to test regenerate-then-fallback)."""

    def __init__(self, script: dict | None = None, default: CompanionOutput | None = None, word_crisis: bool = False):
        self.script = script or {}
        self.default = default or CompanionOutput(
            reply="It sounds like today has been really heavy, and that makes sense. Did I get that right?\nWould it help to tell me a bit more about what happened?")
        self.calls: list[tuple[str, list[dict]]] = []
        self.wording_calls: list[tuple[str, str]] = []
        self._word_crisis = word_crisis

    def respond(self, system: str, messages: list[dict]) -> CompanionOutput | None:
        self.calls.append((system, messages))
        text = messages[-1]["content"].lower()
        for key, res in self.script.items():
            if key.lower() in text:
                if isinstance(res, list):
                    return res.pop(0) if res else None
                return res
        return self.default

    def word_crisis(self, script: str, instruction: str, messages: list[dict]) -> str | None:
        self.wording_calls.append((script, instruction))
        return script if self._word_crisis else None


@pytest.fixture
def settings():
    return Settings(_env_file=None, database_url="sqlite://", use_llm_classifier=False, use_llm_guard=False)


@pytest.fixture
def env(settings):
    db = make_session_factory(settings.database_url)()
    llm = FakeLLM()

    class Env:
        pass

    e = Env()
    e.settings, e.db, e.llm = settings, db, llm
    e.comp = Companion(settings, db, llm, RiskGate(None), OutputGuard(None))
    e.uid = "user-1"

    def onboard(uid=e.uid):
        e.comp.handle(uid, "hi")
        e.comp.handle(uid, "yes")

    e.onboard = onboard
    yield e
    db.close()
