"""Model specs and provider calls via the OpenAI Python SDK (SPEC §4, §5).

Providers: "openai" (default base URL) and "together"
(base_url https://api.together.xyz/v1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Provider = Literal["openai", "together"]
Message = dict[str, Any]
ToolSpec = dict[str, Any]


@dataclass(frozen=True)
class ModelSpec:
    """A model entry from config/models.yaml. Prices are USD per million tokens."""

    provider: Provider
    model_id: str
    price_in: float
    price_out: float
    native_tools: bool


@dataclass
class ModelResponse:
    """One completion: text, parsed tool calls, token usage and cost."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def complete(spec: ModelSpec, messages: list[Message], tools: list[ToolSpec]) -> ModelResponse:
    """Call the model at temperature 0 with retries, caching and cost tracking.

    Uses native tool calling when ``spec.native_tools`` is true, otherwise the
    plain-text JSON tool protocol.
    """
    raise NotImplementedError
