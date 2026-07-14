"""Per-turn latency oracle. Aggregate percentiles are computed by the runner."""

from __future__ import annotations

from ..schemas.result import Check
from .base import TurnContext, make_check


def evaluate(ctx: TurnContext) -> list[Check]:
    limit = ctx.expectation.max_latency_ms
    if limit is None:
        return []
    return [
        make_check(
            "max_latency",
            "latency",
            ctx.response.latency_ms <= limit,
            f"turn took {ctx.response.latency_ms:.0f}ms, over the {limit}ms budget",
            severity="major",
            metric="performance.latency",
        )
    ]
