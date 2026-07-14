"""Report-side schemas: coverage, divergences, human review queue."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DivergenceKind = Literal[
    "candidate_regression",
    "reference_limitation",
    "acceptable_wording_difference",
    "requires_human_review",
]


class CoverageRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    case_ids: list[str] = Field(default_factory=list)
    automated: bool = False
    human_review_only: bool = False
    status: str = "untested"


class Divergence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    turn_index: int
    field: str
    reference: Any = None
    candidate: Any = None
    kind: DivergenceKind
    rationale: str = ""


class HumanReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    question: str
    response: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    reason: str
    severity: str = "major"
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    reviewer_notes: str = ""
