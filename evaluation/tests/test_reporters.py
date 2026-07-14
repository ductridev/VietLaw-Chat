"""Reporters must render every artifact and never hide a blocker."""

from __future__ import annotations

import json
from xml.etree import ElementTree as ET

from evaluation.reporters import (
    console_reporter,
    coverage,
    html_reporter,
    json_reporter,
    junit_reporter,
    markdown_reporter,
)
from evaluation.runners import metrics as metrics_module
from evaluation.schemas.config import ThresholdsConfig
from evaluation.schemas.report import HumanReviewItem
from evaluation.schemas.result import CaseResult, Check, CheckStatus, RunResult, TurnResult


def build_run() -> RunResult:
    passing = CaseResult(
        case_id="ok_001",
        title="A passing case",
        suite="semantic",
        severity="major",
        requirement_ids=["API-ANALYZE-001"],
        turns=[
            TurnResult(
                index=1,
                op="analyze",
                http_status=200,
                latency_ms=120.0,
                checks=[Check(name="ok", oracle="semantic", status=CheckStatus.PASS)],
            )
        ],
    ).finalize()

    failing = CaseResult(
        case_id="bad_001",
        title="A fabricated source",
        suite="rag",
        severity="blocker",
        requirement_ids=["RAG-SRC-001"],
        turns=[
            TurnResult(
                index=1,
                op="analyze",
                http_status=200,
                latency_ms=300.0,
                checks=[
                    Check(
                        name="no_fabricated_source",
                        oracle="source",
                        status=CheckStatus.FAIL,
                        severity="blocker",
                        message="source id 'civil_deposit_999' does not exist",
                        metric="rag.fabricated_source",
                    )
                ],
            )
        ],
    ).finalize()

    run = RunResult(
        run_id="20260713T120000Z-abc123",
        suite="full",
        target="http://127.0.0.1:8010",
        started_at="2026-07-13T12:00:00Z",
        finished_at="2026-07-13T12:01:00Z",
        seed=20260713,
        git_commit="deadbee",
        python_version="3.11.2",
        cases=[passing, failing],
    )
    run.metrics = metrics_module.compute(run.cases, ThresholdsConfig.load())
    run.latency = metrics_module.latency_summary([120.0, 300.0])
    return run


def test_console_shows_the_blocker_and_fails():
    run = build_run()
    output = console_reporter.render(run, colour=False)

    assert "BLOCKER" in output
    assert "bad_001" in output
    assert "RESULT: FAIL" in output
    assert run.ok is False


def test_json_reporter_writes_every_artifact(tmp_path):
    run = build_run()
    review = [
        HumanReviewItem(
            case_id="ok_001",
            question="Chủ nhà giữ cọc?",
            reason="answer makes a legal claim",
            severity="major",
        )
    ]
    json_reporter.write(run, tmp_path, human_review=review)

    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["verdict"] == "fail"
    assert summary["blocker_failures"] == ["bad_001"]
    assert summary["totals"]["total"] == 2

    lines = (tmp_path / "cases.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2

    assert (tmp_path / "failures" / "bad_001.json").exists()
    assert not (tmp_path / "failures" / "ok_001.json").exists()
    assert json.loads((tmp_path / "human_review.json").read_text())[0]["case_id"] == "ok_001"


def test_markdown_reporter_reports_coverage_gaps(tmp_path):
    run = build_run()
    markdown_reporter.write(run, tmp_path)
    report = (tmp_path / "report.md").read_text()

    assert "**Verdict: FAIL**" in report
    assert "[BLOCKER]" in report
    assert "Requirement coverage" in report
    assert "Coverage gaps" in report, "a report that cannot state its gaps is not honest"
    assert (tmp_path / "coverage_matrix.csv").exists()


def test_junit_is_valid_xml_with_failures(tmp_path):
    run = build_run()
    junit_reporter.write(run, tmp_path)
    tree = ET.fromstring((tmp_path / "junit.xml").read_text())

    testcases = tree.findall(".//testcase")
    assert {tc.get("name") for tc in testcases} == {"ok_001", "bad_001"}
    failures = tree.findall(".//failure")
    assert len(failures) == 1
    assert "BLOCKER" in failures[0].get("message", "")


def test_html_report_is_self_contained(tmp_path):
    run = build_run()
    html_reporter.write(run, tmp_path)
    page = (tmp_path / "report.html").read_text()

    assert page.startswith("<!doctype html>")
    assert "bad_001" in page
    assert "FAIL" in page
    assert "http://" not in page.split("<style>")[1].split("</style>")[0], "CSS must not fetch remote assets"
    assert "<script src=" not in page


def test_coverage_matrix_marks_untested_requirements():
    run = build_run()
    rows = coverage.build_matrix(run)
    by_id = {r.requirement_id: r for r in rows}

    assert by_id["API-ANALYZE-001"].status == "pass"
    assert by_id["RAG-SRC-001"].status == "fail"
    assert by_id["AI-CORE-001"].status == "untested", "black-box-untestable requirements must be visible"
    assert coverage.gaps(rows), "the matrix must be able to report gaps"


def test_legal_coverage_declares_its_limits():
    inventory = coverage.legal_coverage()
    assert inventory["corpus"]["snippet_count"] == 26
    assert inventory["claim_limits"]
    assert "administrative" in inventory["domains"]
    assert inventory["domains"]["administrative"]["source_count"] == 0
