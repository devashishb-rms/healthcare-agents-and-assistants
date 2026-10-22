"""Thin Anthropic client wrapper: one place for auth headers, structured output and error handling."""
from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from .config import Settings

log = logging.getLogger("saathi.llm")


def make_client(settings: Settings) -> anthropic.Anthropic:
    headers = {"anthropic-workspace-id": settings.anthropic_workspace_id} if settings.anthropic_workspace_id else None
    return anthropic.Anthropic(api_key=settings.anthropic_api_key or None, default_headers=headers)


def structured_call(
    client: anthropic.Anthropic,
    *,
    model: str,
    system: str,
    messages: list[dict],
    schema: dict,
    effort: str = "low",
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    """One JSON-schema-constrained call. Returns the parsed dict, or None on refusal / malformed output.

    Callers treat None as "unknown" and fall back to their deterministic path.
    """
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
        return None
    if resp.stop_reason == "refusal":
        log.warning("model %s refused", model)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.error("bad JSON from %s: %s", model, text[:200])
        return None
