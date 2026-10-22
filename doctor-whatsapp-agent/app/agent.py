"""LLM agent: one call per inbound patient message, with a manual tool loop and a JSON-schema-constrained final answer."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

import anthropic
from pydantic import BaseModel, Field

from .prompts import CLASSIFICATION_SCHEMA, SYSTEM_PROMPT
from .tools import TOOL_DEFINITIONS, ToolBox

log = logging.getLogger("sevadesk.agent")


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    calls: int = 0


class AgentResult(BaseModel):
    classification: str = "CLINICAL"
    language: str = "en"
    action: str = "DRAFT_FOR_DOCTOR"
    reply_to_patient: str = ""
    note_for_doctor: str = ""
    flags: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)


@dataclass
class AgentContext:
    patient_wa_id: str
    history: list[dict]              # [{"role": "user"|"assistant", "content": str}]
    prompt_vars: dict
    kb_context: str = ""
    attachments: list[str] = field(default_factory=list)   # human-readable descriptions, e.g. "voice note transcript: ..."


class LLM(Protocol):
    def run(self, ctx: AgentContext, patient_text: str) -> AgentResult: ...


class ClaudeAgent:
    def __init__(self, toolbox: ToolBox, model: str, effort: str = "low", enable_fallbacks: bool = False, client: anthropic.Anthropic | None = None, api_key: str | None = None, workspace_id: str | None = None):
        self.toolbox = toolbox
        self.model = model
        self.effort = effort
        self.enable_fallbacks = enable_fallbacks
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = client or anthropic.Anthropic(api_key=api_key, default_headers=headers)

    def _system(self, ctx: AgentContext) -> list[dict]:
        text = SYSTEM_PROMPT.format(kb_context=ctx.kb_context or "(none)", **ctx.prompt_vars)
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    def _create(self, **kwargs):
        if self.enable_fallbacks:
            return self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        return self.client.messages.create(**kwargs)

    def run(self, ctx: AgentContext, patient_text: str) -> AgentResult:
        user_text = patient_text
        if ctx.attachments:
            user_text += "\n\n[Attachments]\n" + "\n".join(ctx.attachments)
        messages = [*ctx.history, {"role": "user", "content": user_text}]
        usage = Usage()

        def account(resp) -> None:
            u = resp.usage
            usage.calls += 1
            usage.input_tokens += u.input_tokens or 0
            usage.output_tokens += u.output_tokens or 0
            usage.cache_read_input_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
            usage.cache_creation_input_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0

        for _ in range(6):   # bounded tool loop
            resp = self._create(
                model=self.model,
                max_tokens=2048,
                system=self._system(ctx),
                messages=messages,
                tools=TOOL_DEFINITIONS,
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": CLASSIFICATION_SCHEMA}},
            )
            account(resp)
            if resp.stop_reason == "refusal":
                log.warning("model refused; falling back to draft-for-doctor")
                return AgentResult(
                    classification="CLINICAL", action="DRAFT_FOR_DOCTOR",
                    reply_to_patient=f"Thank you for your message. Dr. {ctx.prompt_vars['doctor_name']} will reply to you personally.",
                    note_for_doctor="Model declined to answer; please review the patient's message.", flags=["model_refusal"],
                )
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                        try:
                            out = self.toolbox.dispatch(block.name, args, ctx.patient_wa_id)
                            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, ensure_ascii=False)})
                        except Exception as e:  # noqa: BLE001
                            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(e), "is_error": True})
                messages.append({"role": "user", "content": results})
                continue
            text = next((b.text for b in resp.content if b.type == "text"), "")
            try:
                result = AgentResult.model_validate(json.loads(text))
                result.usage = usage
                return result
            except (json.JSONDecodeError, ValueError) as e:
                log.error("bad agent JSON (%s): %s", e, text[:300])
                break
        return AgentResult(
            classification="CLINICAL", action="DRAFT_FOR_DOCTOR",
            reply_to_patient=f"Thank you for your message. Dr. {ctx.prompt_vars['doctor_name']} will reply to you personally.",
            note_for_doctor="Agent could not produce a structured answer; please review.", flags=["agent_error"],
        )
