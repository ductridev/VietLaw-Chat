"""Result types produced by runners and consumed by reporters."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .case import Severity


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


class Check(BaseModel):
    """One oracle assertion about one turn."""

    model_config = ConfigDict(extra="forbid")

    name: str
    oracle: str
    status: CheckStatus
    severity: Severity = "major"
    message: str = ""
    metric: str | None = None
    """Optional metric bucket this check feeds, e.g. `rag.fabricated_source`."""

    @property
    def failed(self) -> bool:
        return self.status in (CheckStatus.FAIL, CheckStatus.ERROR)


class TurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    op: str
    request: dict[str, Any] = Field(default_factory=dict)
    http_status: int | None = None
    response: Any = None
    latency_ms: float = 0.0
    transport_error: str | None = None
    checks: list[Check] = Field(default_factory=list)

    @property
    def failed_checks(self) -> list[Check]:
        return [c for c in self.checks if c.failed]


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    title: str
    suite: str
    severity: Severity
    tags: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    generated: bool = False
    status: CheckStatus = CheckStatus.PASS
    turns: list[TurnResult] = Field(default_factory=list)
    duration_ms: float = 0.0
    human_review_reasons: list[str] = Field(default_factory=list)

    @property
    def checks(self) -> list[Check]:
        return [c for t in self.turns for c in t.checks]

    @property
    def failed_checks(self) -> list[Check]:
        return [c for c in self.checks if c.failed]

    def finalize(self) -> CaseResult:
        failed = self.failed_checks
        if any(c.status == CheckStatus.ERROR for c in failed):
            self.status = CheckStatus.ERROR
        elif failed:
            self.status = CheckStatus.FAIL
        else:
            self.status = CheckStatus.PASS
        return self

    @property
    def blocker_failed(self) -> bool:
        return self.status != CheckStatus.PASS and any(
            c.severity == "blocker" for c in self.failed_checks
        )


class MetricValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    numerator: int = 0
    denominator: int = 0
    threshold: float | None = None
    comparator: str | None = None
    passed: bool | None = None
    """None means no threshold configured, so the metric is informational."""


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    suite: str
    target: str
    started_at: str
    finished_at: str | None = None
    seed: int = 0
    git_commit: str | None = None
    python_version: str = ""
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    cases: list[CaseResult] = Field(default_factory=list)
    metrics: list[MetricValue] = Field(default_factory=list)
    latency: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.status == CheckStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if c.status == CheckStatus.FAIL)

    @property
    def errored(self) -> int:
        return sum(1 for c in self.cases if c.status == CheckStatus.ERROR)

    @property
    def skipped(self) -> int:
        return sum(1 for c in self.cases if c.status == CheckStatus.SKIP)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def blocker_failures(self) -> list[CaseResult]:
        return [c for c in self.cases if c.blocker_failed]

    @property
    def threshold_failures(self) -> list[MetricValue]:
        return [m for m in self.metrics if m.passed is False]

    @property
    def ok(self) -> bool:
        """A run passes only when no blocker failed AND every threshold held.

        An aggregate pass rate can never mask a blocker: this is the single
        place that decision is made.
        """
        return not self.blocker_failures and not self.threshold_failures
