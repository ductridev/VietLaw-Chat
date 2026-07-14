"""Human-readable terminal output."""

from __future__ import annotations

from ..schemas.result import CheckStatus, RunResult

BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def _colour(text: str, colour: str, enabled: bool) -> str:
    return f"{colour}{text}{RESET}" if enabled else text


def render(run: RunResult, colour: bool = True, max_failures: int = 20) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append(_colour(f"VietLaw-Chat evaluation — suite '{run.suite}'", BOLD, colour))
    lines.append(f"  target       {run.target}")
    lines.append(f"  run id       {run.run_id}")
    lines.append(f"  seed         {run.seed}   git {run.git_commit or 'n/a'}   python {run.python_version}")
    lines.append("")

    lines.append(
        f"  cases        {run.total}   "
        + _colour(f"passed {run.passed}", GREEN, colour)
        + "   "
        + _colour(f"failed {run.failed}", RED if run.failed else DIM, colour)
        + "   "
        + _colour(f"errors {run.errored}", RED if run.errored else DIM, colour)
    )
    lines.append(f"  pass rate    {run.pass_rate:.1%}")
    if run.latency:
        lines.append(
            f"  latency      p50 {run.latency.get('p50_ms', 0):.0f}ms   "
            f"p95 {run.latency.get('p95_ms', 0):.0f}ms   max {run.latency.get('max_ms', 0):.0f}ms"
        )
    lines.append("")

    lines.append(_colour("  Metrics vs thresholds", BOLD, colour))
    for metric in run.metrics:
        if metric.threshold is None:
            continue
        mark = "PASS" if metric.passed else "FAIL" if metric.passed is False else "info"
        tint = GREEN if metric.passed else RED if metric.passed is False else DIM
        lines.append(
            f"    {_colour(mark.ljust(4), tint, colour)}  {metric.name:<38} "
            f"{metric.value:.3f}  (need {metric.comparator} {metric.threshold})  "
            f"[{metric.numerator}/{metric.denominator}]"
        )
    lines.append("")

    failures = [c for c in run.cases if c.status != CheckStatus.PASS]
    if failures:
        lines.append(_colour(f"  Failures ({len(failures)})", BOLD, colour))
        for case in failures[:max_failures]:
            tag = "BLOCKER" if case.blocker_failed else case.severity.upper()
            lines.append(f"    {_colour(tag, RED if case.blocker_failed else YELLOW, colour)} {case.case_id}")
            for check in case.failed_checks[:4]:
                lines.append(f"        - [{check.oracle}] {check.name}: {check.message}")
        if len(failures) > max_failures:
            lines.append(f"    … and {len(failures) - max_failures} more (see report.md)")
        lines.append("")

    if run.blocker_failures:
        lines.append(
            _colour(
                f"  {len(run.blocker_failures)} BLOCKER case(s) failed — the suite fails "
                "regardless of the aggregate pass rate.",
                RED,
                colour,
            )
        )
    for note in run.notes:
        lines.append(_colour(f"  note: {note}", YELLOW, colour))

    verdict = "PASS" if run.ok else "FAIL"
    lines.append("")
    lines.append(_colour(f"  RESULT: {verdict}", GREEN if run.ok else RED, colour))
    lines.append("")
    return "\n".join(lines)
