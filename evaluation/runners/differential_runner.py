"""Run the same cases against a reference and a candidate backend.

The candidate is judged on its own merits by the normal oracles. The reference
is used only to *explain* differences — backend_lite is a deterministic
template engine, not a legal authority, so a divergence is a question, not a
verdict.
"""

from __future__ import annotations

import platform
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..clients.api_client import ApiClient
from ..dataset import load_corpus
from ..oracles import differential_oracle
from ..schemas.case import load_cases_from_dir
from ..schemas.config import SuitesConfig, ThresholdsConfig
from ..schemas.report import Divergence
from ..schemas.result import CaseResult, Check, RunResult
from . import metrics as metrics_module
from .case_runner import CaseExecution, CaseRunner, error_result
from .suite_runner import CASES_DIR, RunOptions, select_cases


@dataclass
class DifferentialExecution:
    reference_url: str
    candidate_url: str
    suite: str
    divergences: list[Divergence] = field(default_factory=list)
    reference_run: RunResult | None = None
    candidate_run: RunResult | None = None
    compared_cases: int = 0
    identical_cases: int = 0
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def regressions(self) -> list[Divergence]:
        return [d for d in self.divergences if d.kind == "candidate_regression"]

    @property
    def candidate_normal_failures(self) -> list[Check]:
        """Critical normal-oracle evidence that differential must never mask."""
        if self.candidate_run is None:
            return []
        return [
            check
            for case in self.candidate_run.cases
            for check in case.failed_checks
            if check.oracle in {"contract", "source", "safety"}
        ]

    @property
    def ok(self) -> bool:
        # Differential comparison supplements the candidate's normal run; it
        # never replaces it. In particular, identical broken responses on both
        # sides can produce no raw divergence, but the candidate must still fail
        # its contract/source/safety oracles and blocking thresholds.
        return (
            self.compared_cases > 0
            and self.candidate_run is not None
            and self.candidate_run.ok
            and not self.candidate_normal_failures
            and not self.regressions
        )

    def report_dict(self) -> dict[str, Any]:
        """Return the complete, reproducible differential artifact payload."""
        return {
            "reference_url": self.reference_url,
            "candidate_url": self.candidate_url,
            "suite": self.suite,
            "compared_cases": self.compared_cases,
            "materially_identical_cases": self.identical_cases,
            "verdict": "pass" if self.ok else "fail",
            "counts": self.counts,
            "candidate_normal_failure_count": len(self.candidate_normal_failures),
            "divergences": [d.model_dump(mode="json") for d in self.divergences],
            "reference_run": self.reference_run.model_dump(mode="json") if self.reference_run else None,
            "candidate_run": self.candidate_run.model_dump(mode="json") if self.candidate_run else None,
            "reference_run_verdict": (
                "pass" if self.reference_run and self.reference_run.ok else "fail"
            ),
            "candidate_run_verdict": (
                "pass" if self.candidate_run and self.candidate_run.ok else "fail"
            ),
        }


def _new_run(target: str, suite: str, seed: int, role: str, case_count: int) -> RunResult:
    now = datetime.now(timezone.utc).isoformat()
    return RunResult(
        run_id=f"differential-{role}-{uuid.uuid4().hex[:8]}",
        suite=suite,
        target=target,
        started_at=now,
        seed=seed,
        python_version=platform.python_version(),
        config_snapshot={
            "mode": "experimental_differential",
            "role": role,
            "case_count": case_count,
        },
    )


def _safe_run(runner: CaseRunner, case) -> CaseExecution:
    """Convert an unexpected runner exception into visible oracle evidence."""
    try:
        return runner.run(case)
    except Exception as exc:  # noqa: BLE001 - a broken side must not abort comparison
        return CaseExecution(result=error_result(case, f"{type(exc).__name__}: {exc}"))


def _finalize_run(
    run: RunResult,
    results: list[CaseResult],
    thresholds: ThresholdsConfig,
    *,
    strict: bool,
) -> None:
    results.sort(key=lambda result: result.case_id)
    if strict:
        for result in results:
            for check in result.failed_checks:
                check.severity = "blocker"
    run.cases = results
    run.metrics = metrics_module.compute(results, thresholds)
    latencies = [
        turn.latency_ms
        for result in results
        for turn in result.turns
        if turn.http_status is not None
    ]
    run.latency = metrics_module.latency_summary(latencies)
    run.finished_at = datetime.now(timezone.utc).isoformat()


def _respect_normal_oracle_direction(
    divergences: list[Divergence],
    reference_result: CaseResult,
    candidate_result: CaseResult,
) -> None:
    """Do not blame a clean candidate when the reference fails the case.

    Raw field heuristics are intentionally conservative, but a reference that
    violates the same declarative case/oracles is not ground truth. When the
    candidate has no normal-oracle failure and the reference does, downgrade
    heuristic candidate regressions to an explicit reference limitation.
    """

    if not reference_result.failed_checks or candidate_result.failed_checks:
        return
    failed_names = ", ".join(check.name for check in reference_result.failed_checks[:4])
    for divergence in divergences:
        if divergence.kind != "candidate_regression":
            continue
        divergence.kind = "reference_limitation"
        divergence.rationale = (
            "reference normal oracles failed while candidate normal oracles passed "
            f"({failed_names}); the reference cannot establish a candidate regression"
        )


def run_differential(
    reference_url: str,
    candidate_url: str,
    options: RunOptions,
    suites: SuitesConfig | None = None,
    thresholds: ThresholdsConfig | None = None,
) -> DifferentialExecution:
    suites = suites or SuitesConfig.load()
    thresholds = thresholds or ThresholdsConfig.load()
    definition = suites.suites[options.suite]
    cases = [c for c in select_cases(load_cases_from_dir(CASES_DIR), definition, options) if c.differential_compare]

    corpus = load_corpus()
    execution = DifferentialExecution(
        reference_url=reference_url,
        candidate_url=candidate_url,
        suite=options.suite,
    )
    execution.reference_run = _new_run(reference_url, options.suite, options.seed, "reference", len(cases))
    execution.candidate_run = _new_run(candidate_url, options.suite, options.seed, "candidate", len(cases))
    reference_results: list[CaseResult] = []
    candidate_results: list[CaseResult] = []

    with (
        ApiClient(reference_url, timeout=options.timeout, retries=options.retries) as ref_client,
        ApiClient(candidate_url, timeout=options.timeout, retries=options.retries) as cand_client,
    ):
        ref_client.wait_until_ready(attempts=3)
        cand_client.wait_until_ready(attempts=3)
        ref_runner = CaseRunner(ref_client, corpus=corpus, run_id="ref")
        cand_runner = CaseRunner(cand_client, corpus=corpus, run_id="cand")

        for case in cases:
            ref_exec = _safe_run(ref_runner, case)
            cand_exec = _safe_run(cand_runner, case)
            reference_results.append(ref_exec.result)
            candidate_results.append(cand_exec.result)
            execution.compared_cases += 1

            case_divergences: list[Divergence] = []
            for index, (ref_response, cand_response) in enumerate(
                zip(ref_exec.raw_responses, cand_exec.raw_responses), start=1
            ):
                case_divergences.extend(
                    differential_oracle.compare(case.id, index, ref_response, cand_response)
                )
            if len(ref_exec.raw_responses) != len(cand_exec.raw_responses):
                case_divergences.append(
                    Divergence(
                        case_id=case.id,
                        turn_index=min(len(ref_exec.raw_responses), len(cand_exec.raw_responses)) + 1,
                        field="response_count",
                        reference=len(ref_exec.raw_responses),
                        candidate=len(cand_exec.raw_responses),
                        kind=(
                            "candidate_regression"
                            if len(cand_exec.raw_responses) < len(ref_exec.raw_responses)
                            else "requires_human_review"
                        ),
                        rationale="the two backends did not complete the same number of case turns",
                    )
                )
            _respect_normal_oracle_direction(
                case_divergences,
                ref_exec.result,
                cand_exec.result,
            )
            material = [d for d in case_divergences if d.kind != "acceptable_wording_difference"]
            if not material:
                execution.identical_cases += 1
            execution.divergences.extend(case_divergences)

    _finalize_run(execution.reference_run, reference_results, thresholds, strict=options.strict)
    _finalize_run(execution.candidate_run, candidate_results, thresholds, strict=options.strict)
    execution.counts = differential_oracle.summarize(execution.divergences)
    return execution
