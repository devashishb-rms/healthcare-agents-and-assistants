"""Tiny REPL for manual testing: `.venv/bin/python chat.py` (real models) or `--fake` (rules + scripts only)."""
import sys

from app.companion import build_companion
from app.config import get_settings
from app.memory import make_session_factory


def main() -> None:
    settings = get_settings()
    live = "--fake" not in sys.argv
    db = make_session_factory(settings.database_url)()
    c = build_companion(settings, db, live=live)
    uid = "cli-user"
    print(f"[Saathi {'live' if live else 'fake'}] type a message; 'quit' to exit")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("quit", "exit"):
            break
        r = c.handle(uid, text)
        print(f"\n{r.text}\n   [{r.mode} risk={r.risk_level} handoff={r.handoff_requested} stage={r.crisis_stage} flags={r.flags} guard={r.guard_violations}]\n")


if __name__ == "__main__":
    main()
