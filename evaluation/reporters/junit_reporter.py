"""JUnit XML for CI consumption."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from ..schemas.result import CheckStatus, RunResult


def render(run: RunResult) -> str:
    suites = ET.Element("testsuites", name=f"vietlaw-eval-{run.suite}")
    by_suite: dict[str, list] = {}
    for case in run.cases:
        by_suite.setdefault(case.suite, []).append(case)

    for suite_name in sorted(by_suite):
        cases = by_suite[suite_name]
        failures = sum(1 for c in cases if c.status == CheckStatus.FAIL)
        errors = sum(1 for c in cases if c.status == CheckStatus.ERROR)
        suite_el = ET.SubElement(
            suites,
            "testsuite",
            name=suite_name,
            tests=str(len(cases)),
            failures=str(failures),
            errors=str(errors),
            time=f"{sum(c.duration_ms for c in cases) / 1000:.3f}",
        )
        for case in cases:
            case_el = ET.SubElement(
                suite_el,
                "testcase",
                classname=f"{run.suite}.{case.suite}",
                name=case.case_id,
                time=f"{case.duration_ms / 1000:.3f}",
            )
            if case.status == CheckStatus.PASS:
                continue
            tag = "error" if case.status == CheckStatus.ERROR else "failure"
            detail = ET.SubElement(
                case_el,
                tag,
                message=f"{len(case.failed_checks)} check(s) failed"
                + (" [BLOCKER]" if case.blocker_failed else ""),
                type=case.severity,
            )
            detail.text = "\n".join(
                f"[{c.oracle}] {c.name}: {c.message}" for c in case.failed_checks
            )
    return ET.tostring(suites, encoding="unicode", xml_declaration=True)


def write(run: RunResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "junit.xml").write_text(render(run), encoding="utf-8")
