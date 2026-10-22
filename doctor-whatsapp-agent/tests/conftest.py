import pytest

from app.agent import AgentContext, AgentResult
from app.config import Settings
from app.db import make_session_factory
from app.orchestrator import Orchestrator
from app.tools import Calendar, ClinicKB, Reports, ToolBox
from app.whatsapp import WhatsAppClient

DOCTOR = "919999900000"
PATIENT = "919999900001"


class FakeLLM:
    """Scripted stand-in for Claude. `script` maps a substring of the patient text to an AgentResult."""

    def __init__(self, script: dict[str, AgentResult] | None = None, default: AgentResult | None = None):
        self.script = script or {}
        self.default = default or AgentResult(classification="ADMIN", action="SEND", reply_to_patient="Sure, the clinic is open 10-1 and 5-8.")
        self.calls: list[tuple[AgentContext, str]] = []

    def run(self, ctx: AgentContext, patient_text: str) -> AgentResult:
        self.calls.append((ctx, patient_text))
        for key, res in self.script.items():
            if key.lower() in patient_text.lower():
                return res
        return self.default


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, dry_run=True, doctor_control_number=DOCTOR, doctor_name="Mehta",
        database_url=f"sqlite:///{tmp_path}/t.db", kb_path="data/clinic_kb.json",
        calendar_path=str(tmp_path / "cal.json"), reports_path="data/reports.json", backoff_minutes=10,
    )


@pytest.fixture
def env(settings, tmp_path):
    (tmp_path / "cal.json").write_text('{"doctor_status": "in OPD", "busy_until": "1 pm", "slots": [{"id": "s1", "start": "2099-01-05T10:00", "booked_by": null}]}')
    Session = make_session_factory(settings.database_url)
    wa = WhatsAppClient("", "", dry_run=True)
    toolbox = ToolBox(ClinicKB(settings.kb_path), Calendar(settings.calendar_path), Reports(settings.reports_path))
    llm = FakeLLM()
    db = Session()

    class Env:
        pass

    e = Env()
    e.settings, e.db, e.wa, e.llm, e.toolbox = settings, db, wa, llm, toolbox
    e.orch = Orchestrator(settings, db, wa, llm, toolbox)
    yield e
    db.close()
