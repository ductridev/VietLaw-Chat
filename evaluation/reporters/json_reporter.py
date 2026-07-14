"""JSON artifacts: summary.json, cases.jsonl, failures/, human_review.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..schemas.report import Divergence, HumanReviewItem
from ..schemas.result import CheckStatus, RunResult


def summary_dict(run: RunResult) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "suite": run.suite,
        "target": run.target,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "seed": run.seed,
        "git_commit": run.git_commit,
        "python_version": run.python_version,
        "totals": {
            "total": run.total,
            "passed": run.passed,
            "failed": run.failed,
            "errors": run.errored,
            "skipped": run.skipped,
            "pass_rate": round(run.pass_rate, 4),
        },
        "verdict": "pass" if run.ok else "fail",
        "blocker_failures": [c.case_id for c in run.blocker_failures],
        "threshold_failures": [m.name for m in run.threshold_failures],
        "metrics": [m.model_dump() for m in run.metrics],
        "latency": {k: round(v, 1) for k, v in run.latency.items()},
        "top_failures": [
            {
                "case_id": c.case_id,
                "severity": c.severity,
                "blocker": c.blocker_failed,
                "checks": [
                    {"name": ch.name, "oracle": ch.oracle, "message": ch.message} for ch in c.failed_checks[:5]
                ],
            }
            for c in sorted(run.cases, key=lambda c: (not c.blocker_failed, c.case_id))
            if c.status != CheckStatus.PASS
        ][:25],
        "config_snapshot": run.config_snapshot,
        "notes": run.notes,
    }


def write(
    run: RunResult,
    out_dir: Path,
    human_review: list[HumanReviewItem] | None = None,
    divergences: list[Divergence] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "summary.json").write_text(
        json.dumps(summary_dict(run), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (out_dir / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for case in run.cases:
            handle.write(json.dumps(case.model_dump(mode="json"), ensure_ascii=False) + "\n")

    failures_dir = out_dir / "failures"
    failures_dir.mkdir(exist_ok=True)
    for case in run.cases:
        if case.status == CheckStatus.PASS:
            continue
        (failures_dir / f"{case.case_id}.json").write_text(
            json.dumps(case.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if human_review is not None:
        (out_dir / "human_review.json").write_text(
            json.dumps([item.model_dump() for item in human_review], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if divergences is not None:
        (out_dir / "divergences.json").write_text(
            json.dumps([d.model_dump() for d in divergences], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
