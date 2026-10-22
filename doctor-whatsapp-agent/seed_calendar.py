"""Generate data/calendar.json with real upcoming slots: next 7 clinic days (Mon-Sat), 10:00-12:40 and 17:00-19:40, every 20 min."""
import json
from datetime import datetime, timedelta
from pathlib import Path

out = Path("data/calendar.json")
existing = json.loads(out.read_text()) if out.exists() else {}
booked = {s["id"]: s for s in existing.get("slots", []) if s.get("booked_by")}
slots, day, days_added = [], datetime.now().date() + timedelta(days=1), 0
while days_added < 7:
    if day.weekday() < 6:  # Mon-Sat
        for h, m in [(10, 0), (10, 20), (10, 40), (11, 0), (11, 20), (11, 40), (12, 0), (12, 20), (12, 40),
                     (17, 0), (17, 20), (17, 40), (18, 0), (18, 20), (18, 40), (19, 0), (19, 20), (19, 40)]:
            sid = f"{day.isoformat()}-{h:02d}{m:02d}"
            slots.append(booked.get(sid, {"id": sid, "start": f"{day.isoformat()}T{h:02d}:{m:02d}", "booked_by": None}))
        days_added += 1
    day += timedelta(days=1)
out.write_text(json.dumps({"doctor_status": existing.get("doctor_status", "in OPD with patients"),
                           "busy_until": existing.get("busy_until", "1:00 pm today"), "slots": slots}, indent=2))
print(f"wrote {len(slots)} slots to {out}")
