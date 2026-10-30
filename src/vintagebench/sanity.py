"""Sanity agents that need no API (SPEC §4).

Each has the same call interface as a model: given the conversation and the
available tools, return a ModelResponse.
"""

from __future__ import annotations

from typing import Protocol

from vintagebench.models import Message, ModelResponse, ToolSpec


class SanityAgent(Protocol):
    """Callable with the same interface as ``models.complete`` minus the spec."""

    name: str

    def __call__(self, messages: list[Message], tools: list[ToolSpec]) -> ModelResponse: ...


def oracle(messages: list[Message], tools: list[ToolSpec]) -> ModelResponse:
    """Answer from the correct vintage each turn: 100% on all metrics, 0 leakage."""
    raise NotImplementedError


def always_yes(messages: list[Message], tools: list[ToolSpec]) -> ModelResponse:
    """Always answer yes; expected ~50% accuracy."""
    raise NotImplementedError


def leaker(messages: list[Message], tools: list[ToolSpec]) -> ModelResponse:
    """Read the latest vintage regardless of date; leakage flagged wherever values differ."""
    raise NotImplementedError


def never_update(messages: list[Message], tools: list[ToolSpec]) -> ModelResponse:
    """Answer correctly as of turn 1 and never change; update_correct only on controls."""
    raise NotImplementedError
