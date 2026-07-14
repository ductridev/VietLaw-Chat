"""Decide which responses an automated oracle is not competent to judge.

Automated checks can prove a response is *well-formed, grounded and safe*.
They cannot prove it is *legally correct*. Anything that makes a substantive
legal claim, or that the harness is unsure about, is routed to a human.
"""

from __future__ import annotations

import re

from ..dataset import normalize
from ..schemas.report import HumanReviewItem
from .base import TurnContext, generated_text

# Wording that asserts legal substance rather than navigation guidance.
#
# Article/decree references are matched as regexes, not substrings: a bare
# "dieu " also matches "điều kiện" (conditions) and "điều khoản" (terms), which
# are ordinary words. Flagging those buried the real citations under noise and
# made the queue unreadable — a review queue nobody reads reviews nothing.
LEGAL_CLAIM_PATTERNS = (
    r"\bdieu \d+",          # "Điều 328"
    r"\bnghi dinh \d+",     # "Nghị định 100"
    r"\bthong tu \d+",
    r"\bbo luat \w+ \d{4}", # "Bộ luật Dân sự 2015"
    r"\bkhoan \d+ dieu \d+",
    r"\bmuc phat (la|tu) ",
    r"\bbi phat tien",
    r"\bthoi hieu (khoi kien|la)",
    r"\btheo luat,? ban (chac chan|co quyen)",
    r"\bphap luat quy dinh rang",
)
LOW_CONFIDENCE = 0.5


def review_reasons(ctx: TurnContext) -> list[str]:
    if not ctx.is_success_analyze:
        return []
    reasons: list[str] = []
    body = ctx.body

    if ctx.case.human_review.required and ctx.case.human_review.reason:
        reasons.append(ctx.case.human_review.reason)

    text = normalize(generated_text(body))
    claims = [m.group(0) for p in LEGAL_CLAIM_PATTERNS if (m := re.search(p, text))]
    if claims:
        reasons.append(
            f"answer makes substantive legal claims ({claims[:3]}) that only a lawyer can verify"
        )

    confidence = body.get("confidence")
    if isinstance(confidence, dict):
        low = {k: v for k, v in confidence.items() if isinstance(v, (int, float)) and v < LOW_CONFIDENCE}
        if low:
            reasons.append(f"backend reported low confidence {low}")

    if body.get("decision") in {"answer_with_guidance", "recommend_professional_help"} and not body.get("sources"):
        reasons.append("guidance was given with zero sources; legal grounding is unverified")

    return reasons


def build_item(ctx: TurnContext, reasons: list[str]) -> HumanReviewItem:
    body = ctx.body
    return HumanReviewItem(
        case_id=ctx.case.id,
        question=ctx.turn.question or "",
        response={
            k: body.get(k)
            for k in ("domain", "risk_level", "decision", "summary", "clarifying_questions", "checklist", "next_steps")
        },
        sources=[s for s in (body.get("sources") or []) if isinstance(s, dict)],
        reason="; ".join(reasons),
        severity=ctx.case.severity,
    )
