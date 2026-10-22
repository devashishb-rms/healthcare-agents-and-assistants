"""Thin WhatsApp Cloud API client (Meta Graph API). DRY_RUN prints instead of sending."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("sevadesk.whatsapp")


@dataclass
class WhatsAppClient:
    token: str
    phone_number_id: str
    api_version: str = "v22.0"
    dry_run: bool = True
    sent: list[dict] = field(default_factory=list)   # captured outbound messages (useful in tests / dry run)

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def send_text(self, to: str, text: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text[:4096]},
        }
        self.sent.append({"to": to, "text": text})
        if self.dry_run:
            log.info("[DRY RUN] -> %s: %s", to, text)
            return {"dry_run": True}
        r = httpx.post(f"{self._base}/{self.phone_number_id}/messages", headers=self._headers(), json=payload, timeout=20)
        r.raise_for_status()
        return r.json()

    def send_template(self, to: str, template_name: str, language: str, components: list[dict] | None = None) -> dict:
        """Business-initiated message outside the 24-hour window. The template must be approved by Meta and the
        recipient must have opted in. `components` follows the Graph API shape, e.g.
        [{"type": "body", "parameters": [{"type": "text", "text": "Rahul"}, ...]}]."""
        template = {"name": template_name, "language": {"code": language}}
        if components:
            template["components"] = components
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template", "template": template}
        self.sent.append({"to": to, "template": template_name, "language": language, "components": components or []})
        if self.dry_run:
            log.info("[DRY RUN] -> %s: template %s (%s) %s", to, template_name, language, components or [])
            return {"dry_run": True}
        r = httpx.post(f"{self._base}/{self.phone_number_id}/messages", headers=self._headers(), json=payload, timeout=20)
        r.raise_for_status()
        return r.json()

    def mark_read(self, message_id: str) -> None:
        if self.dry_run:
            return
        payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        try:
            httpx.post(f"{self._base}/{self.phone_number_id}/messages", headers=self._headers(), json=payload, timeout=10)
        except httpx.HTTPError as e:  # non-fatal
            log.warning("mark_read failed: %s", e)

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Returns (bytes, mime_type). Media URLs expire after 5 minutes, so fetch immediately."""
        if self.dry_run:
            return b"", "application/octet-stream"
        meta = httpx.get(f"{self._base}/{media_id}", headers=self._headers(), timeout=20)
        meta.raise_for_status()
        info = meta.json()
        blob = httpx.get(info["url"], headers={"Authorization": f"Bearer {self.token}"}, timeout=60)
        blob.raise_for_status()
        return blob.content, info.get("mime_type", "application/octet-stream")
