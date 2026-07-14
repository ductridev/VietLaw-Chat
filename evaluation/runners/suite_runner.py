"""Load cases, select a suite, execute, aggregate, apply thresholds."""

from __future__ import annotations

import platform
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..clients.api_client import ApiClient, BackendUnavailable
from ..dataset import load_corpus
from ..schemas.case import EvalCase, load_cases_from_dir
from ..schemas.config import SuiteDef, SuitesConfig, ThresholdsConfig
from ..schemas.report import HumanReviewItem
from ..schemas.result import CaseResult, RunResult
from ..transforms.metamorphic import expand
from ..transforms.review_registry import normalized_question_key
from . import metrics as metrics_module
from .case_runner import CaseRunner, error_result

CASES_DIR = Path(__file__).resolve().parents[1] / "cases"


@dataclass
class RunOptions:
    base_url: str
    suite: str = "smoke"
    case_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    seed: int = 20260713
    workers: int = 4
    timeout: float = 30.0
    retries: int = 0
    fail_fast: bool = False
    strict: bool = False
    """strict promotes every failed check to blocker severity."""


@dataclass
class SuiteExecution:
    run: RunResult
    human_review: list[HumanReviewItem] = field(default_factory=list)


def select_cases(
    all_cases: list[EvalCase],
    definition: SuiteDef,
    options: RunOptions,
) -> list[EvalCase]:
    """Deterministic selection: filter, then expand metamorphic, then sort by id."""
    if definition.required_seed is not None and options.seed != definition.required_seed:
        raise ValueError(
            f"this reviewed suite requires seed {definition.required_seed}; "
            f"got {options.seed}. Re-review generated content before changing the seed"
        )

    explicit_case_ids = set(getattr(definition, "explicit_case_ids", []))
    selected = [
        case
        for case in all_cases
        if (not explicit_case_ids or case.id in explicit_case_ids)
        if (not definition.include_suites or case.suite in definition.include_suites)
        and (not definition.include_tags or set(case.tags) & set(definition.include_tags))
        and not (set(case.tags) & set(definition.exclude_tags))
    ]

    if definition.metamorphic_variants > 0:
        selected.extend(expand(all_cases, definition.metamorphic_variants, options.seed))

    generated_review_statuses = set(getattr(definition, "generated_review_statuses", []))
    if generated_review_statuses:
        selected = [
            case
            for case in selected
            if not case.generated
            or any(f"review:{status}" in case.tags for status in generated_review_statuses)
        ]
    if getattr(definition, "require_gate_eligible", False):
        selected = [case for case in selected if not case.generated or "gate_eligible" in case.tags]

    if getattr(definition, "deduplicate_normalized_questions", False):
        # Curated cases may intentionally repeat a question to exercise a
        # different endpoint/oracle. Generated variants add no coverage when
        # they normalize to any curated question, so seed those keys first.
        seen_questions = {
            normalized_question_key(turn.question or "")
            for case in selected
            if not case.generated
            for turn in case.turns
            if turn.question
        }
        deduplicated: list[EvalCase] = []
        for case in selected:
            if not case.generated:
                deduplicated.append(case)
                continue
            question = case.turns[0].question if len(case.turns) == 1 else None
            key = normalized_question_key(question or "")
            if key and key in seen_questions:
                continue
            if key:
                seen_questions.add(key)
            deduplicated.append(case)
        selected = deduplicated
    if not definition.include_generated:
        selected = [c for c in selected if not c.generated or c.suite == "metamorphic"]

    if options.case_ids:
        wanted = set(options.case_ids)
        selected = [c for c in selected if c.id in wanted]
    if options.tags:
        wanted_tags = set(options.tags)
        selected = [c for c in selected if set(c.tags) & wanted_tags]

    selected.sort(key=lambda c: c.id)
    if definition.max_cases is not None:
        selected = selected[: definition.max_cases]
    return selected


def _git_commit() -> str | None:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def run_suite(
    options: RunOptions,
    suites: SuitesConfig | None = None,
    thresholds: ThresholdsConfig | None = None,
    cases_dir: Path = CASES_DIR,
) -> SuiteExecution:
    suites = suites or SuitesConfig.load()
    thresholds = thresholds or ThresholdsConfig.load()

    if options.suite not in suites.suites:
        raise KeyError(f"unknown suite {options.suite!r}; known: {sorted(suites.suites)}")
    definition = suites.suites[options.suite]

    all_cases = load_cases_from_dir(cases_dir)
    selected = select_cases(all_cases, definition, options)

    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    run = RunResult(
        run_id=run_id,
        suite=options.suite,
        target=options.base_url,
        started_at=datetime.now(timezone.utc).isoformat(),
        seed=options.seed,
        git_commit=_git_commit(),
        python_version=platform.python_version(),
        config_snapshot={
            "suite": definition.model_dump(),
            "workers": options.workers,
            "timeout": options.timeout,
            "retries": options.retries,
            "strict": options.strict,
            "case_count": len(selected),
            "thresholds": {k: v.model_dump() for k, v in thresholds.thresholds.items()},
        },
    )

    corpus = load_corpus()
    human_review: list[HumanReviewItem] = []
    results: list[CaseResult] = []
    latencies: list[float] = []

    def execute(case: EvalCase) -> tuple[CaseResult, list[HumanReviewItem], list[float]]:
        with ApiClient(options.base_url, timeout=options.timeout, retries=options.retries) as client:
            runner = CaseRunner(client, corpus=corpus, run_id=run_id)
            try:
                execution = runner.run(case)
            except Exception as exc:  # noqa: BLE001 - a runner crash must fail the case, not the run
                return error_result(case, f"{type(exc).__name__}: {exc}"), [], []
            turn_latencies = [t.latency_ms for t in execution.result.turns if t.http_status is not None]
            return execution.result, execution.human_review, turn_latencies

    # A backend that is not listening is a run-level condition (exit code 3),
    # not four hundred individual case failures.
    with ApiClient(options.base_url, timeout=min(options.timeout, 10.0)) as probe:
        probe.wait_until_ready(attempts=3, delay=0.6)

    if options.fail_fast or options.workers <= 1:
        for case in selected:
            result, review, case_latencies = execute(case)
            results.append(result)
            human_review.extend(review)
            latencies.extend(case_latencies)
            if options.fail_fast and result.status != "pass":
                run.notes.append(f"fail-fast: stopped at {case.id}")
                break
    else:
        with ThreadPoolExecutor(max_workers=options.workers) as pool:
            for result, review, case_latencies in pool.map(execute, selected):
                results.append(result)
                human_review.extend(review)
                latencies.extend(case_latencies)

    results.sort(key=lambda r: r.case_id)
    if options.strict:
        for result in results:
            for check in result.failed_checks:
                check.severity = "blocker"

    run.cases = results
    run.metrics = metrics_module.compute(results, thresholds)
    run.latency = metrics_module.latency_summary(latencies)
    run.finished_at = datetime.now(timezone.utc).isoformat()

    if not selected:
        run.notes.append("no cases matched the selection; treat this run as inconclusive")
    return SuiteExecution(run=run, human_review=human_review)


__all__ = ["RunOptions", "SuiteExecution", "run_suite", "select_cases", "BackendUnavailable"]
