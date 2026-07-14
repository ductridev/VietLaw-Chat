"""Semantic oracle: classification against acceptable sets, phrase constraints.

Deliberately never asserts an exact full answer. A legal answer is free-form;
pinning its wording would only measure how well the backend memorised a golden
string. What is pinned: the classification triple, required concepts, forbidden
claims, and regex patterns.
"""

from __future__ import annotations

import re

from ..schemas.result import Check
from .base import TurnContext, contains_phrase, find_outside_refusal, generated_text, make_check


def evaluate(ctx: TurnContext) -> list[Check]:
    if not ctx.is_success_analyze:
        return []

    body = ctx.body
    expectation = ctx.expectation
    checks: list[Check] = []

    for field, acceptable, metric in (
        ("domain", expectation.acceptable_domain, "semantic.domain"),
        ("risk_level", expectation.acceptable_risk, "semantic.risk"),
        ("decision", expectation.acceptable_decision, "semantic.decision"),
    ):
        if not acceptable:
            continue
        actual = body.get(field)
        checks.append(
            make_check(
                f"acceptable_{field}",
                "semantic",
                actual in acceptable,
                f"{field}={actual!r} is not in the acceptable set {acceptable}",
                severity="blocker" if ctx.case.is_blocker else "major",
                metric=metric,
            )
        )

    text = generated_text(body)

    for phrase in expectation.must_include:
        checks.append(
            make_check(
                f"must_include::{phrase}",
                "semantic",
                contains_phrase(text, phrase),
                f"answer content does not mention {phrase!r}",
                severity="major",
                metric="semantic.must_include",
            )
        )

    for phrase in expectation.must_not_include:
        checks.append(
            make_check(
                f"must_not_include::{phrase}",
                "semantic",
                not find_outside_refusal(text, phrase),
                f"answer asserts forbidden phrase {phrase!r} outside a refusal context",
                severity="blocker",
                metric="semantic.must_not_include",
            )
        )

    for pattern in expectation.must_match:
        checks.append(
            make_check(
                f"must_match::{pattern}",
                "semantic",
                re.search(pattern, text, re.IGNORECASE | re.MULTILINE) is not None,
                f"answer content does not match /{pattern}/",
                severity="major",
            )
        )
    for pattern in expectation.must_not_match:
        checks.append(
            make_check(
                f"must_not_match::{pattern}",
                "semantic",
                re.search(pattern, text, re.IGNORECASE | re.MULTILINE) is None,
                f"answer content matches forbidden pattern /{pattern}/",
                severity="major",
            )
        )

    # An unsupported answer must not smuggle legal guidance back in.
    if body.get("decision") == "unsupported":
        checks.append(
            make_check(
                "unsupported_has_no_sources",
                "semantic",
                not body.get("sources"),
                "an unsupported response must not cite legal sources",
                severity="major",
                metric="semantic.unsupported_clean",
            )
        )
    return checks
