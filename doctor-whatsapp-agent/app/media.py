"""Voice-note transcription (optional). Uses Sarvam's speech-to-text REST API when SARVAM_API_KEY is set.
Endpoint/field names follow Sarvam's public docs as of Oct 2026; verify against https://docs.sarvam.ai if it errors."""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("sevadesk.media")


def transcribe(audio: bytes, mime: str, api_key: str) -> str | None:
    if not api_key or not audio:
        return None
    try:
        ext = "ogg" if "ogg" in mime else ("mp3" if "mpeg" in mime else "m4a")
        r = httpx.post(
            "https://api.sarvam.ai/speech-to-text",
            headers={"api-subscription-key": api_key},
            files={"file": (f"note.{ext}", audio, mime)},
            data={"model": "saaras:v4", "language_code": "unknown"},
            timeout=60,
        )
        r.raise_for_status()
        return r.json().get("transcript")
    except httpx.HTTPError as e:
        log.warning("transcription failed: %s", e)
        return None
