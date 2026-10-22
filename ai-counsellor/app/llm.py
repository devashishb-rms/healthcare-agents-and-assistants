"""Thin Anthropic client wrapper: one place for auth headers, structured output and error handling."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

from .config import Settings

log = logging.getLogger("saathi.llm")


def make_client(settings: Settings) -> anthropic.Anthropic:
    headers = {"anthropic-workspace-id": settings.anthropic_workspace_id} if settings.anthropic_workspace_id else None
    return anthropic.Anthropic(api_key=settings.anthropic_api_key or None, default_headers=headers)


@dataclass
class LLMResult:
    """status: ok | refusal | truncated | bad_json | api_error. Only `ok` carries data."""
    status: str
    data: dict[str, Any] | None = None
    raw: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def model_answered_badly(self) -> bool:
        """The model produced *something* we could not use. Safety callers treat this as 'unsure' and escalate.
        An API error is different: the model never saw the text, so the deterministic rules alone decide."""
        return self.status in ("refusal", "truncated", "bad_json")


def structured_call(
    client: anthropic.Anthropic,
    *,
    model: str,
    system: str,
    messages: list[dict],
    schema: dict,
    effort: str = "low",
    max_tokens: int = 1024,
) -> LLMResult:
    """One JSON-schema-constrained call."""
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIError as e:  # network/auth/rate-limit: never crash the safety path
        log.error("anthropic API error (%s): %s", model, e)
        return LLMResult("api_error", detail=str(e))
    if resp.stop_reason == "refusal":
        log.warning("model %s refused", model)
        return LLMResult("refusal")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    if resp.stop_reason == "max_tokens":
        log.error("output from %s truncated at max_tokens=%d: %s", model, max_tokens, text[:200])
        return LLMResult("truncated", raw=text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.error("bad JSON from %s (%s): %s", model, e, text[:200])
        return LLMResult("bad_json", raw=text, detail=str(e))
    if not isinstance(data, dict):
        return LLMResult("bad_json", raw=text, detail="not an object")
    return LLMResult("ok", data=data, raw=text)
