"""Per-model price table (USD per million tokens) and cost estimation for `llm_usage` audit rows.

Prices are Anthropic first-party API list prices as of Oct 2026. Cache writes are billed at 1.25x the input
price (5-minute TTL, which is what app/agent.py uses). Update this table when prices change; unknown models fall
back to `DEFAULT_MODEL` and are flagged as assumed in the console.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

PRICES_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-opus-5-5":   {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-opus-5":     {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-sonnet-5":   {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5":  {"input": 0.10, "output": 0.50,  "cache_read": 0.01, "cache_write": 0.125},
}
DEFAULT_MODEL = "claude-opus-5-5"


@dataclass
class UsageRow:
    """One parsed `llm_usage` audit row."""
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    calls: int = 0
    assumed_model: bool = False     # True when the row carried no model and we priced it as `model`

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_input_tokens + self.cache_creation_input_tokens

    @property
    def usd(self) -> float:
        return estimate_usd(self.model, self.input_tokens, self.output_tokens,
                            self.cache_read_input_tokens, self.cache_creation_input_tokens)


def resolve_model(model: str | None, fallback: str | None = None) -> tuple[str, bool]:
    """Return (model_used_for_pricing, assumed). Unknown or empty models fall back to `fallback`, then DEFAULT_MODEL."""
    if model and model in PRICES_USD_PER_MTOK:
        return model, False
    if fallback and fallback in PRICES_USD_PER_MTOK:
        return fallback, True
    return DEFAULT_MODEL, True


def estimate_usd(model: str, input_tokens: int = 0, output_tokens: int = 0,
                 cache_read: int = 0, cache_write: int = 0) -> float:
    p = PRICES_USD_PER_MTOK.get(model) or PRICES_USD_PER_MTOK[DEFAULT_MODEL]
    return (input_tokens * p["input"] + output_tokens * p["output"]
            + cache_read * p["cache_read"] + cache_write * p["cache_write"]) / 1_000_000


def parse_usage_detail(detail: str, fallback_model: str | None = None) -> UsageRow | None:
    """Parse the JSON written by orchestrator (`Usage.model_dump_json()`). Returns None for unparseable rows."""
    try:
        d = json.loads(detail or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    model, assumed = resolve_model(d.get("model"), fallback_model)
    return UsageRow(
        model=model, assumed_model=assumed,
        input_tokens=int(d.get("input_tokens", 0) or 0),
        output_tokens=int(d.get("output_tokens", 0) or 0),
        cache_read_input_tokens=int(d.get("cache_read_input_tokens", 0) or 0),
        cache_creation_input_tokens=int(d.get("cache_creation_input_tokens", 0) or 0),
        calls=int(d.get("calls", 0) or 0),
    )
