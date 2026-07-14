"""Oracles decide whether an observed response satisfies a case.

Each oracle takes a TurnContext and returns Checks. They are pure functions of
(case, response, corpus) — no I/O, no backend imports — so they can be unit
tested against hand-built mutant responses (see tests/test_negative_controls.py).
"""

from . import (
    contract_oracle,
    conversation_oracle,
    human_review_oracle,
    latency_oracle,
    safety_oracle,
    semantic_oracle,
    source_oracle,
)
from .base import TurnContext, make_check

# Order matters only for report readability, not for correctness.
TURN_ORACLES = (
    contract_oracle,
    semantic_oracle,
    source_oracle,
    safety_oracle,
    conversation_oracle,
    latency_oracle,
)

__all__ = [
    "TURN_ORACLES",
    "TurnContext",
    "make_check",
    "contract_oracle",
    "semantic_oracle",
    "source_oracle",
    "safety_oracle",
    "conversation_oracle",
    "latency_oracle",
    "human_review_oracle",
]
