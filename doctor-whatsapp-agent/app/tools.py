"""Deterministic tools the agent may call. Facts (slots, fees, report status) only ever come from here."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


class ClinicKB:
    """Tiny keyword-overlap retriever over a JSON list of {"q","a","tags"}. Swap for pgvector later."""

    def __init__(self, path: str):
        p = Path(path)
        self.entries: list[dict] = json.loads(p.read_text()) if p.exists() else []

    @staticmethod
    def _tokens(s: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9ऀ-ॿ]+", s.lower()) if len(t) > 2}

    def search(self, query: str, k: int = 4) -> list[dict]:
        q = self._tokens(query)
        scored = []
        for e in self.entries:
            doc = self._tokens(e.get("q", "") + " " + " ".join(e.get("tags", [])))
            score = len(q & doc)
            if score:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:k]]

    def render(self, hits: list[dict]) -> str:
        if not hits:
            return "(no matching entries)"
        return "\n".join(f"- Q: {h['q']}\n  A: {h['a']}" for h in hits)


class Calendar:
    """JSON-backed slot store: {"slots":[{"id":"...","start":"2026-10-21T10:00","booked_by":null}], "doctor_status": "...", "busy_until": "..."}"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.data: dict[str, Any] = json.loads(self.path.read_text()) if self.path.exists() else {"slots": []}

    def _save(self) -> None:
        if self.path.parent.exists():
            self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))

    def status(self) -> dict:
        return {
            "doctor_status": self.data.get("doctor_status", "in OPD"),
            "busy_until": self.data.get("busy_until"),
        }

    def free_slots(self, on: str | None = None, limit: int = 6) -> list[dict]:
        out = []
        for s in self.data.get("slots", []):
            if s.get("booked_by"):
                continue
            if on and not s["start"].startswith(on):
                continue
            if s["start"] < datetime.now().strftime("%Y-%m-%dT%H:%M"):
                continue
            out.append({"id": s["id"], "start": s["start"]})
            if len(out) >= limit:
                break
        return out

    def book(self, slot_id: str, patient_wa_id: str, patient_name: str | None) -> dict:
        for s in self.data.get("slots", []):
            if s["id"] == slot_id:
                if s.get("booked_by") and s["booked_by"] != patient_wa_id:
                    return {"ok": False, "error": "slot already booked"}
                s["booked_by"] = patient_wa_id
                s["patient_name"] = patient_name
                self._save()
                return {"ok": True, "slot": {"id": s["id"], "start": s["start"]}}
        return {"ok": False, "error": "no such slot"}

    def cancel(self, patient_wa_id: str) -> dict:
        n = 0
        for s in self.data.get("slots", []):
            if s.get("booked_by") == patient_wa_id:
                s["booked_by"] = None
                s["patient_name"] = None
                n += 1
        self._save()
        return {"ok": True, "cancelled": n}

    def my_bookings(self, patient_wa_id: str) -> list[dict]:
        return [{"id": s["id"], "start": s["start"]} for s in self.data.get("slots", []) if s.get("booked_by") == patient_wa_id]


class Reports:
    """JSON list of {"name","dob","status","ready_on"}; identity = name + dob match."""

    def __init__(self, path: str):
        p = Path(path)
        self.rows: list[dict] = json.loads(p.read_text()) if p.exists() else []

    def status(self, name: str, dob: str) -> dict:
        for r in self.rows:
            if r["name"].strip().lower() == name.strip().lower() and r["dob"] == dob:
                return {"found": True, "status": r["status"], "ready_on": r.get("ready_on")}
        return {"found": False}


TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "list_free_slots",
        "description": "List available appointment slots. Optional date filter YYYY-MM-DD.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": ["string", "null"], "description": "YYYY-MM-DD or null"}},
            "required": ["date"],
            "additionalProperties": False,
        },
    },
    {
        "name": "book_slot",
        "description": "Book an appointment slot for this patient. Use a slot id from list_free_slots. Confirm with the patient first.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"slot_id": {"type": "string"}, "patient_name": {"type": ["string", "null"]}},
            "required": ["slot_id", "patient_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_my_bookings",
        "description": "Cancel all of this patient's upcoming bookings. Confirm with the patient first.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "my_bookings",
        "description": "Show this patient's upcoming bookings.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "report_status",
        "description": "Check whether a lab report is ready. Requires the patient's full name and date of birth (YYYY-MM-DD) for identity verification. Never reveals the contents of the report.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "dob": {"type": "string"}},
            "required": ["name", "dob"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_clinic_kb",
        "description": "Search the clinic knowledge base (fees, timings, directions, preparation instructions, FAQs written by the doctor).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


class ToolBox:
    def __init__(self, kb: ClinicKB, calendar: Calendar, reports: Reports):
        self.kb, self.calendar, self.reports = kb, calendar, reports

    def dispatch(self, name: str, args: dict, patient_wa_id: str) -> Any:
        if name == "list_free_slots":
            return self.calendar.free_slots(args.get("date") or None)
        if name == "book_slot":
            return self.calendar.book(args["slot_id"], patient_wa_id, args.get("patient_name"))
        if name == "cancel_my_bookings":
            return self.calendar.cancel(patient_wa_id)
        if name == "my_bookings":
            return self.calendar.my_bookings(patient_wa_id)
        if name == "report_status":
            return self.reports.status(args["name"], args["dob"])
        if name == "search_clinic_kb":
            return self.kb.search(args["query"])
        return {"error": f"unknown tool {name}"}


def today_str() -> str:
    return date.today().isoformat()
