"""Interactive terminal simulator: chat as a patient (or as the doctor with --doctor) without WhatsApp.
Usage:  .venv/bin/python simulate.py [--doctor] [--from 919999900001]
Requires ANTHROPIC_API_KEY (or `ant auth login`). Runs in DRY_RUN regardless of .env."""
from __future__ import annotations

import argparse
import os
import uuid

os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./sevadesk-sim.db")

from app.main import Inbound, process, settings, wa  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--doctor", action="store_true", help="send messages as the doctor control number")
parser.add_argument("--from", dest="sender", default="919999900001")
args = parser.parse_args()
sender = settings.doctor_control_number or "919999900000" if args.doctor else args.sender
print(f"Simulating as {'DOCTOR' if args.doctor else 'patient'} {sender}. Mode default={settings.default_mode}. Ctrl-C to quit.")
while True:
    try:
        text = input("you> ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not text:
        continue
    wa.sent.clear()
    r = process(Inbound(wa_message_id=f"sim-{uuid.uuid4()}", from_wa_id=sender, text=text))
    for s in wa.sent:
        tag = "to DOCTOR" if s["to"] == settings.doctor_control_number else f"to {s['to']}"
        print(f"  [{tag}] {s['text']}")
    print(f"  -> {r}")
