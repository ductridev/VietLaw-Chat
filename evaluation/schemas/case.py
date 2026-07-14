"""Evaluation case schema.

A case is declarative data. It never contains executable logic, and it never
asserts an exact full answer text: legal answers are free-form, so oracles work
on acceptable value sets, source identity, invariants and phrase constraints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["blocker", "critical", "major", "minor"]
Suite = Literal[
    "contract",
    "session",
    "persistence",
    "semantic",
    "rag",
    "safety",
    "adversarial",
    "conversation",
    "language",
    "robustness",
    "metamorphic",
    "load",
]
Op = Literal[
    "analyze",
    "health",
    "chat_create",
    "chat_list",
    "chat_detail",
    "chat_delete",
]
SessionMode = Literal["fresh", "same", "attacker"]

DOMAINS = {"civil_dispute", "traffic", "household_business", "administrative", "high_risk", "unknown"}
RISKS = {"low", "medium", "high"}
DECISIONS = {
    "answer_with_guidance",
    "ask_clarifying_questions",
    "recommend_professional_help",
    "refuse_unsafe_request",
    "unsupported",
}
ERROR_CODES = {"invalid_request", "chat_not_found", "retrieval_error", "llm_error", "internal_error"}


class Expectation(BaseModel):
    """What a single turn's response must satisfy.

    Every field is optional: a turn only declares the dimensions it actually
    pins down. Undeclared dimensions are still covered by global invariants.
    """

    model_config = ConfigDict(extra="forbid")

    http_status: int | None = None
    error_code: str | None = None

    acceptable_domain: list[str] = Field(default_factory=list)
    acceptable_risk: list[str] = Field(default_factory=list)
    acceptable_decision: list[str] = Field(default_factory=list)

    requires_sources: bool | None = None
    requires_no_sources: bool | None = None
    min_sources: int | None = None
    max_sources: int | None = None
    required_source_ids: list[str] = Field(default_factory=list)
    allowed_source_ids: list[str] = Field(default_factory=list)
    forbidden_source_ids: list[str] = Field(default_factory=list)

    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    must_match: list[str] = Field(default_factory=list)
    must_not_match: list[str] = Field(default_factory=list)

    exact_safety_notice: bool = True
    assistant_content_type: Literal["structured", "text"] | None = None
    expected_metadata: dict[str, Any] = Field(default_factory=dict)

    safety_class: Literal["unsafe_hard", "safe_contrast", "escalation"] | None = None
    """Which safety rule this TURN is held to.

    Scoped per turn, never per case: a conversation case whose turn 2 is unsafe
    has a turn 1 that is deliberately safe, and holding turn 1 to "must refuse"
    (or turn 2 to "must not refuse") invents failures that are not there.
    Single-turn cases derive this from their tags automatically.
    """

    requires_persistence: bool = False
    requires_reload_equivalence: bool = False
    requires_new_chat: bool | None = None

    max_latency_ms: int | None = None

    @model_validator(mode="after")
    def _check_enums(self) -> Expectation:
        for field_name, allowed in (
            ("acceptable_domain", DOMAINS),
            ("acceptable_risk", RISKS),
            ("acceptable_decision", DECISIONS),
        ):
            bad = set(getattr(self, field_name)) - allowed
            if bad:
                raise ValueError(f"{field_name} has unsupported values: {sorted(bad)}")
        if self.error_code is not None and self.error_code not in ERROR_CODES:
            raise ValueError(f"error_code {self.error_code!r} is not an MVP error code")

        for field_name in ("required_source_ids", "allowed_source_ids", "forbidden_source_ids"):
            source_ids = getattr(self, field_name)
            if len(source_ids) != len(set(source_ids)):
                raise ValueError(f"{field_name} contains duplicate source IDs")

        if self.min_sources is not None and self.min_sources < 0:
            raise ValueError("min_sources cannot be negative")
        if self.max_sources is not None and self.max_sources < 0:
            raise ValueError("max_sources cannot be negative")
        if (
            self.min_sources is not None
            and self.max_sources is not None
            and self.min_sources > self.max_sources
        ):
            raise ValueError("min_sources cannot exceed max_sources")

        if self.requires_sources and self.requires_no_sources:
            raise ValueError("requires_sources and requires_no_sources are mutually exclusive")
        if self.requires_sources and self.max_sources == 0:
            raise ValueError("requires_sources cannot be combined with max_sources=0")
        if self.requires_no_sources and (
            self.required_source_ids
            or self.allowed_source_ids
            or (self.min_sources is not None and self.min_sources > 0)
            or (self.max_sources is not None and self.max_sources > 0)
        ):
            raise ValueError("requires_no_sources cannot be combined with source-positive constraints")

        required = set(self.required_source_ids)
        allowed = set(self.allowed_source_ids)
        forbidden = set(self.forbidden_source_ids)
        overlap = required & forbidden
        if overlap:
            raise ValueError(
                "required_source_ids overlap forbidden_source_ids: " f"{sorted(overlap)}"
            )
        overlap = allowed & forbidden
        if overlap:
            raise ValueError(
                "allowed_source_ids overlap forbidden_source_ids: " f"{sorted(overlap)}"
            )
        if allowed and not required <= allowed:
            raise ValueError(
                "required_source_ids must be included in allowed_source_ids: "
                f"{sorted(required - allowed)}"
            )
        if self.max_sources is not None and len(required) > self.max_sources:
            raise ValueError("max_sources is smaller than required_source_ids")
        if self.min_sources is not None and allowed and self.min_sources > len(allowed):
            raise ValueError("min_sources exceeds the number of allowed_source_ids")
        return self


class Turn(BaseModel):
    """One API operation inside a case."""

    model_config = ConfigDict(extra="forbid")

    op: Op = "analyze"
    question: str | None = None
    user_type: str | None = None
    language: str | None = None
    title: str | None = None

    reuse_chat_id: bool = False
    session: SessionMode = "same"
    chat_id: str | None = None
    """Literal chat_id override. `$prev` resolves to the previous turn's chat_id."""

    omit_session_id: bool = False
    omit_question: bool = False
    raw_body: Any | None = None
    """Bypass payload construction entirely (malformed-input testing)."""
    raw_body_is_text: bool = False
    query_overrides: dict[str, Any] = Field(default_factory=dict)

    expected: Expectation = Field(default_factory=Expectation)

    @model_validator(mode="after")
    def _check_op(self) -> Turn:
        if self.op == "analyze" and self.question is None and self.raw_body is None and not self.omit_question:
            raise ValueError("analyze turn needs a question, omit_question, or raw_body")
        if self.reuse_chat_id and self.chat_id is not None:
            raise ValueError("reuse_chat_id and an explicit chat_id are mutually exclusive")
        if self.chat_id is not None and not self.chat_id.strip():
            raise ValueError("chat_id cannot be empty")
        return self


class Invariants(BaseModel):
    """Properties enforced on every turn unless explicitly disabled."""

    model_config = ConfigDict(extra="forbid")

    no_fabricated_source: bool = True
    no_deprecated_source: bool = True
    no_cross_session_leak: bool = True
    no_unsafe_tactical_output: bool = True
    no_traceback_leak: bool = True
    no_secret_leak: bool = True
    structured_schema_valid: bool = True


class HumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def _reason_required(self) -> HumanReview:
        if self.required and not self.reason:
            raise ValueError("human_review.required needs a reason")
        return self


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=120)
    title: str
    suite: Suite
    severity: Severity = "major"
    requirement_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    user_type: str = "citizen"
    language: str = "vi"

    question: str | None = None
    """Single-turn shorthand; expanded into `turns` at load time."""
    expected: Expectation | None = None

    turns: list[Turn] = Field(default_factory=list)
    invariants: Invariants = Field(default_factory=Invariants)
    human_review: HumanReview = Field(default_factory=HumanReview)

    metamorphic_group: str | None = None
    source_relevance_topic: str | None = None
    differential_compare: bool = True
    generated: bool = False

    @model_validator(mode="after")
    def _expand(self) -> EvalCase:
        if self.question is not None:
            if self.turns:
                raise ValueError("use either `question` shorthand or `turns`, not both")
            expectation = self.expected or Expectation()
            if expectation.safety_class is None:
                # A single-turn case has exactly one turn, so its safety tag is
                # unambiguous. Multi-turn cases must say which turn they mean.
                for tag in ("unsafe_hard", "safe_contrast", "escalation"):
                    if tag in self.tags:
                        expectation.safety_class = tag  # type: ignore[assignment]
                        break
            self.turns = [Turn(question=self.question, session="fresh", expected=expectation)]
        elif self.expected is not None:
            raise ValueError("top-level `expected` only applies to the `question` shorthand")
        if not self.turns:
            raise ValueError("case must define `question` or at least one turn")
        if not self.requirement_ids:
            raise ValueError("every case must carry at least one requirement id for traceability")

        if self.turns[0].reuse_chat_id:
            raise ValueError("first turn cannot reuse_chat_id because no prior chat exists")
        if self.turns[0].chat_id == "$prev":
            raise ValueError("first turn cannot target $prev because no prior chat exists")
        for index, turn in enumerate(self.turns, start=1):
            if turn.reuse_chat_id and turn.session != "same":
                raise ValueError(
                    f"turn {index}: reuse_chat_id requires session='same', got {turn.session!r}"
                )
            raw_target = (
                isinstance(turn.raw_body, dict)
                and isinstance(turn.raw_body.get("chat_id"), str)
                and bool(turn.raw_body["chat_id"].strip())
            )
            if (
                turn.session == "attacker"
                and turn.op in {"analyze", "chat_detail", "chat_delete"}
                and turn.chat_id is None
                and not turn.reuse_chat_id
                and not raw_target
            ):
                raise ValueError(
                    f"turn {index}: attacker operation requires a target chat_id"
                )

        safety_tags = {tag for tag in self.tags if tag in {"unsafe_hard", "safe_contrast", "escalation"}}
        if len(self.turns) > 1 and safety_tags:
            turn_classes = {
                turn.expected.safety_class
                for turn in self.turns
                if turn.expected.safety_class is not None
            }
            missing = safety_tags - turn_classes
            if missing:
                raise ValueError(
                    "multi-turn safety tag requires a matching per-turn safety_class: "
                    f"{sorted(missing)}"
                )

        for turn in self.turns:
            if turn.user_type is None:
                turn.user_type = self.user_type
            if turn.language is None:
                turn.language = self.language
        # The first turn of a case always starts a fresh session unless a case
        # deliberately models an attacker reusing an existing one.
        if self.turns[0].session == "same":
            self.turns[0].session = "fresh"
        return self

    @property
    def is_blocker(self) -> bool:
        return self.severity == "blocker"


def load_cases_from_dir(root: Path) -> list[EvalCase]:
    """Load every case in `root`, sorted by id for deterministic ordering."""
    cases: dict[str, EvalCase] = {}
    for path in sorted(root.rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = raw.get("cases", [])
        if not isinstance(entries, list):
            raise ValueError(f"{path}: `cases` must be a list")
        for entry in entries:
            case = EvalCase.model_validate(entry)
            if case.id in cases:
                raise ValueError(f"{path}: duplicate case id {case.id!r}")
            cases[case.id] = case
    return [cases[cid] for cid in sorted(cases)]
