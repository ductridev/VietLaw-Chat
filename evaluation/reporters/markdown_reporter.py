"""Markdown run report, including coverage gaps and the human-review queue."""

from __future__ import annotations

from pathlib import Path

from ..schemas.report import HumanReviewItem
from ..schemas.result import CheckStatus, RunResult
from . import coverage


def render(run: RunResult, human_review: list[HumanReviewItem] | None = None) -> str:
    human_review = human_review or []
    lines: list[str] = []
    verdict = "PASS" if run.ok else "FAIL"

    lines.append(f"# VietLaw-Chat evaluation report — `{run.suite}`")
    lines.append("")
    lines.append(f"**Verdict: {verdict}**")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Target | `{run.target}` |")
    lines.append(f"| Run id | `{run.run_id}` |")
    lines.append(f"| Started | {run.started_at} |")
    lines.append(f"| Seed | `{run.seed}` |")
    lines.append(f"| Git commit | `{run.git_commit or 'n/a'}` |")
    lines.append(f"| Python | {run.python_version} |")
    lines.append(f"| Cases | {run.total} |")
    lines.append(f"| Passed | {run.passed} |")
    lines.append(f"| Failed | {run.failed} |")
    lines.append(f"| Errors | {run.errored} |")
    lines.append(f"| Pass rate | {run.pass_rate:.1%} |")
    if run.latency:
        lines.append(f"| Latency p50 / p95 | {run.latency.get('p50_ms', 0):.0f}ms / {run.latency.get('p95_ms', 0):.0f}ms |")
    lines.append("")

    if run.blocker_failures:
        lines.append("> **Blocker failures present.** A blocker failure fails the suite no matter how")
        lines.append("> high the aggregate pass rate is.")
        lines.append("")

    lines.append("## Metrics vs thresholds")
    lines.append("")
    lines.append("| Metric | Value | Threshold | Result | Sample |")
    lines.append("|---|---:|---|---|---|")
    for metric in run.metrics:
        result = "PASS" if metric.passed else "**FAIL**" if metric.passed is False else "info"
        threshold = f"{metric.comparator} {metric.threshold}" if metric.threshold is not None else "—"
        lines.append(
            f"| `{metric.name}` | {metric.value:.3f} | {threshold} | {result} | {metric.numerator}/{metric.denominator} |"
        )
    lines.append("")

    lines.append("## Results by suite")
    lines.append("")
    lines.append("| Suite | Cases | Passed | Failed |")
    lines.append("|---|---:|---:|---:|")
    by_suite: dict[str, list] = {}
    for case in run.cases:
        by_suite.setdefault(case.suite, []).append(case)
    for suite in sorted(by_suite):
        cases = by_suite[suite]
        passed = sum(1 for c in cases if c.status == CheckStatus.PASS)
        lines.append(f"| {suite} | {len(cases)} | {passed} | {len(cases) - passed} |")
    lines.append("")

    failures = [c for c in run.cases if c.status != CheckStatus.PASS]
    lines.append(f"## Failures ({len(failures)})")
    lines.append("")
    if not failures:
        lines.append("None.")
    else:
        for case in sorted(failures, key=lambda c: (not c.blocker_failed, c.case_id)):
            flag = " **[BLOCKER]**" if case.blocker_failed else ""
            lines.append(f"### `{case.case_id}`{flag} — {case.title}")
            lines.append("")
            lines.append(f"- suite: `{case.suite}` · severity: `{case.severity}` · requirements: "
                         f"{', '.join(f'`{r}`' for r in case.requirement_ids) or '—'}")
            for turn in case.turns:
                for check in turn.failed_checks:
                    lines.append(f"- turn {turn.index} · `{check.oracle}` · **{check.name}**: {check.message}")
            lines.append("")
    lines.append("")

    rows = coverage.build_matrix(run)
    gaps = coverage.gaps(rows)
    lines.append("## Requirement coverage")
    lines.append("")
    lines.append(f"- requirements with automated cases: **{len(rows) - len(gaps)}/{len(rows)}**")
    lines.append(f"- requirements with **no** automated case: **{len(gaps)}**")
    lines.append("")
    if gaps:
        lines.append("Coverage gaps (no automated case exercises these):")
        lines.append("")
        catalogue = coverage.load_requirements()
        for row in gaps:
            lines.append(f"- `{row.requirement_id}` — {catalogue.get(row.requirement_id, '')}")
        lines.append("")

    lines.append("## Human review queue")
    lines.append("")
    if not human_review:
        lines.append("No responses required human review in this run.")
    else:
        lines.append(
            f"{len(human_review)} response(s) make legal claims or carry low confidence. "
            "Automated oracles cannot certify legal correctness; these need a qualified reviewer."
        )
        lines.append("")
        lines.append("| Case | Reason |")
        lines.append("|---|---|")
        for item in human_review[:40]:
            lines.append(f"| `{item.case_id}` | {item.reason[:160]} |")
    lines.append("")

    if run.notes:
        lines.append("## Notes")
        lines.append("")
        for note in run.notes:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def write(run: RunResult, out_dir: Path, human_review: list[HumanReviewItem] | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(render(run, human_review), encoding="utf-8")
    (out_dir / "coverage_matrix.csv").write_text(coverage.to_csv(coverage.build_matrix(run)), encoding="utf-8")

    if human_review:
        lines = ["# Human review queue", "", f"Run `{run.run_id}` against `{run.target}`.", ""]
        for item in human_review:
            lines.append(f"## `{item.case_id}` ({item.severity})")
            lines.append("")
            lines.append(f"**Question:** {item.question}")
            lines.append("")
            lines.append(f"**Why flagged:** {item.reason}")
            lines.append("")
            lines.append(f"**Summary:** {item.response.get('summary', '')}")
            lines.append("")
            if item.sources:
                lines.append("**Sources cited:** " + ", ".join(f"`{s.get('id')}`" for s in item.sources))
                lines.append("")
            lines.append(f"**Review status:** {item.review_status}")
            lines.append("")
            lines.append("---")
            lines.append("")
        (out_dir / "human_review.md").write_text("\n".join(lines), encoding="utf-8")
