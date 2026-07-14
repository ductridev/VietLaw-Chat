"""Turn checks into metrics, then compare metrics against thresholds.

Metric names are declared by the oracles (`Check.metric`). Two families:

* rate-of-failure metrics (e.g. `rag.fabricated_source`) → measured as the
  fraction of relevant checks that FAILED;
* rate-of-success metrics (e.g. `safety.hard_unsafe_recall`) → the fraction
  that PASSED.

Which family a metric belongs to is declared here, not guessed, so a threshold
can never be satisfied by reading the metric in the wrong direction.
"""

from __future__ import annotations

import statistics
from typing import Iterable

from ..schemas.config import ThresholdsConfig
from ..schemas.result import CaseResult, CheckStatus, MetricValue

# metric name -> ("failure_rate" | "pass_rate")
METRIC_KIND = {
    "contract.schema_valid": "pass_rate",
    "contract.traceback_leak": "failure_rate",
    "contract.secret_leak": "failure_rate",
    "session.cross_session_leak": "failure_rate",
    "session.owner_disclosure": "failure_rate",
    "safety.notice_coverage": "pass_rate",
    "safety.hard_unsafe_recall": "pass_rate",
    "safety.escalation_recall": "pass_rate",
    "safety.unsafe_content_leak": "failure_rate",
    "safety.safe_contrast_accuracy": "pass_rate",
    "rag.fabricated_source": "failure_rate",
    "rag.deprecated_source": "failure_rate",
    "rag.irrelevant_source": "failure_rate",
    "rag.precision": "pass_rate",
    "rag.recall": "pass_rate",
    "rag.source_presence": "pass_rate",
    "rag.no_source_accuracy": "pass_rate",
    "rag.unsupported_claim": "failure_rate",
    "rag.citation_integrity": "pass_rate",
    "rag.source_usefulness": "pass_rate",
    "rag.top_k_respected": "pass_rate",
    "conversation.reload_equivalence": "pass_rate",
    "conversation.followup_consistency": "pass_rate",
    "conversation.persistence": "pass_rate",
    "conversation.ordering": "pass_rate",
    "conversation.new_chat": "pass_rate",
    "semantic.domain": "pass_rate",
    "semantic.risk": "pass_rate",
    "semantic.decision": "pass_rate",
    "semantic.must_include": "pass_rate",
    "semantic.must_not_include": "pass_rate",
    "semantic.unsupported_clean": "pass_rate",
    "performance.latency": "pass_rate",
}

# Derived metrics computed from case status rather than individual checks.
CASE_RATE_METRICS = {
    "contract.blocker_pass_rate": lambda c: c.suite in {"contract", "session", "persistence"},
    "semantic.curated_pass_rate": lambda c: c.suite in {"semantic", "rag"} and not c.generated,
    "semantic.metamorphic_invariance": lambda c: c.suite == "metamorphic",
    "safety.suite_pass_rate": lambda c: c.suite in {"safety", "adversarial"},
    "conversation.suite_pass_rate": lambda c: c.suite == "conversation",
    "overall.pass_rate": lambda c: True,
}


def compute(cases: list[CaseResult], thresholds: ThresholdsConfig) -> list[MetricValue]:
    metrics: list[MetricValue] = []

    buckets: dict[str, list[CheckStatus]] = {}
    for case in cases:
        for check in case.checks:
            if check.metric:
                buckets.setdefault(check.metric, []).append(check.status)

    for name, statuses in sorted(buckets.items()):
        kind = METRIC_KIND.get(name)
        if kind is None:
            continue
        total = len(statuses)
        if kind == "failure_rate":
            hits = sum(1 for s in statuses if s in (CheckStatus.FAIL, CheckStatus.ERROR))
        else:
            hits = sum(1 for s in statuses if s == CheckStatus.PASS)
        value = hits / total if total else 0.0
        metrics.append(_with_threshold(name, value, hits, total, thresholds))

    for name, predicate in CASE_RATE_METRICS.items():
        subset = [c for c in cases if predicate(c)]
        if not subset:
            continue
        passed = sum(1 for c in subset if c.status == CheckStatus.PASS)
        metrics.append(_with_threshold(name, passed / len(subset), passed, len(subset), thresholds))

    return sorted(metrics, key=lambda m: m.name)


def _with_threshold(
    name: str, value: float, numerator: int, denominator: int, thresholds: ThresholdsConfig
) -> MetricValue:
    passed, definition = thresholds.check(name, value)
    if definition is not None and not definition.blocker:
        # Informational threshold: report the value, never fail the run on it.
        passed = None
    return MetricValue(
        name=name,
        value=value,
        numerator=numerator,
        denominator=denominator,
        threshold=definition.value if definition else None,
        comparator=definition.comparator if definition else None,
        passed=passed,
    )


def latency_summary(latencies: Iterable[float]) -> dict[str, float]:
    values = sorted(latencies)
    if not values:
        return {}
    return {
        "count": float(len(values)),
        "mean_ms": statistics.fmean(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": values[-1],
    }


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[index]
