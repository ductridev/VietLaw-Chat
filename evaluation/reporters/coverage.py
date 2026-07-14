"""Requirement traceability and legal-coverage reporting.

The requirement catalogue is declared in config/requirements.yaml. Anything in
that catalogue with no case is reported as a gap — the coverage matrix is only
honest if it can say "not tested".
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import yaml

from ..schemas.report import CoverageRow
from ..schemas.result import CheckStatus, RunResult

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def load_requirements() -> dict[str, str]:
    path = CONFIG_DIR / "requirements.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {r["id"]: r.get("description", "") for r in data.get("requirements", [])}


def build_matrix(run: RunResult) -> list[CoverageRow]:
    catalogue = load_requirements()
    rows: dict[str, CoverageRow] = {
        rid: CoverageRow(requirement_id=rid, status="untested") for rid in catalogue
    }

    for case in run.cases:
        for rid in case.requirement_ids:
            row = rows.setdefault(rid, CoverageRow(requirement_id=rid, status="untested"))
            row.case_ids.append(case.case_id)
            row.automated = True
            if case.status == CheckStatus.PASS and row.status in ("untested", "pass"):
                row.status = "pass"
            elif case.status != CheckStatus.PASS:
                row.status = "fail"

    for row in rows.values():
        if row.case_ids and not row.automated:
            row.human_review_only = True
    return [rows[k] for k in sorted(rows)]


def gaps(rows: list[CoverageRow]) -> list[CoverageRow]:
    return [row for row in rows if not row.case_ids]


def to_csv(rows: list[CoverageRow]) -> str:
    catalogue = load_requirements()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["requirement_id", "description", "status", "case_count", "case_ids"])
    for row in rows:
        writer.writerow(
            [
                row.requirement_id,
                catalogue.get(row.requirement_id, ""),
                row.status,
                len(row.case_ids),
                " ".join(sorted(row.case_ids)[:12]),
            ]
        )
    return buffer.getvalue()


def legal_coverage() -> dict[str, object]:
    path = CONFIG_DIR / "legal_coverage.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
