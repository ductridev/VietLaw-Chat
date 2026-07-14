"""VietLaw-Chat evaluation CLI.

Exit codes (stable, for CI):
    0  suite met every blocker threshold
    1  assertion/evaluation failure
    2  config/schema/runner error
    3  backend unavailable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .clients.api_client import BackendUnavailable
from .reporters import (
    console_reporter,
    coverage,
    html_reporter,
    json_reporter,
    junit_reporter,
    markdown_reporter,
)
from .runners.suite_runner import CASES_DIR, RunOptions, run_suite
from .schemas.case import load_cases_from_dir
from .schemas.config import EnvironmentsConfig, LoadConfig, SuitesConfig, ThresholdsConfig

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2
EXIT_UNAVAILABLE = 3


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--suite", default="smoke", help="suite name from config/suites.yaml")
    parser.add_argument("--case", action="append", default=[], help="run only this case id (repeatable)")
    parser.add_argument("--tag", action="append", default=[], help="run only cases with this tag (repeatable)")
    parser.add_argument("--seed", type=int, default=20260713, help="seed for generated cases")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--report-dir", type=Path, default=Path("outputs/eval"))
    parser.add_argument("--strict", action="store_true", help="treat every failed check as a blocker")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--json", dest="want_json", action="store_true", default=True)
    parser.add_argument("--no-json", dest="want_json", action="store_false")
    parser.add_argument("--junit", action="store_true", default=True)
    parser.add_argument("--markdown", action="store_true", default=True)
    parser.add_argument("--html", action="store_true", default=True)
    parser.add_argument("--no-color", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evaluation.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate every case, suite and threshold file")
    validate.add_argument("--json", dest="want_json", action="store_true")

    run = sub.add_parser("run", help="run a suite against one backend")
    run.add_argument("--base-url", required=True)
    _add_common(run)

    diff = sub.add_parser("differential", help="compare a candidate backend against a reference")
    diff.add_argument("--reference-url", required=True)
    diff.add_argument("--candidate-url", required=True)
    _add_common(diff)

    load = sub.add_parser("load", help="concurrency and latency measurement")
    load.add_argument("--base-url", required=True)
    load.add_argument("--concurrency", type=int, default=5)
    load.add_argument("--requests", type=int, default=100, help="different-chat request count")
    load.add_argument("--same-chat-requests", type=int, default=20)
    load.add_argument("--profile", default=None, help="named profile from config/load_profiles.yaml")
    load.add_argument("--timeout", type=float, default=30.0)
    load.add_argument("--report-dir", type=Path, default=Path("outputs/eval"))

    faults = sub.add_parser("faults", help="prove the harness detects broken backends (self-test)")
    faults.add_argument("--timeout", type=float, default=3.0)
    faults.add_argument("--report-dir", type=Path, default=Path("outputs/eval"))

    sub.add_parser("coverage", help="print the legal-coverage inventory and requirement catalogue")

    return parser


# -- commands -------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        cases = load_cases_from_dir(CASES_DIR)
        suites = SuitesConfig.load()
        thresholds = ThresholdsConfig.load()
        EnvironmentsConfig.load()
        LoadConfig.load()
        requirements = coverage.load_requirements()
    except Exception as exc:  # noqa: BLE001 - any config error is exit 2
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    cited = {rid for case in cases for rid in case.requirement_ids}
    unknown = sorted(cited - set(requirements))
    uncovered = sorted(set(requirements) - cited)

    by_suite: dict[str, int] = {}
    for case in cases:
        by_suite[case.suite] = by_suite.get(case.suite, 0) + 1

    print(f"cases        {len(cases)} valid")
    for suite in sorted(by_suite):
        print(f"  {suite:<14} {by_suite[suite]}")
    print(f"suites       {len(suites.suites)}: {', '.join(sorted(suites.suites))}")
    print(f"thresholds   {len(thresholds.thresholds)}")
    print(f"requirements {len(requirements)} catalogued, {len(cited)} cited by cases")

    if unknown:
        print(f"\nERROR: cases cite requirement ids that are not in the catalogue: {unknown}", file=sys.stderr)
        return EXIT_CONFIG
    if uncovered:
        print(f"\ncoverage gaps ({len(uncovered)} requirements have no automated case):")
        for rid in uncovered:
            print(f"  - {rid}: {requirements[rid][:100]}")
    print("\nOK")
    return EXIT_OK


def _write_reports(args: argparse.Namespace, execution, out_dir: Path) -> None:
    run = execution.run
    if args.want_json:
        json_reporter.write(run, out_dir, human_review=execution.human_review)
    if args.markdown:
        markdown_reporter.write(run, out_dir, human_review=execution.human_review)
    if args.junit:
        junit_reporter.write(run, out_dir)
    if args.html:
        html_reporter.write(run, out_dir)


def cmd_run(args: argparse.Namespace) -> int:
    options = RunOptions(
        base_url=args.base_url,
        suite=args.suite,
        case_ids=args.case,
        tags=args.tag,
        seed=args.seed,
        workers=args.workers,
        timeout=args.timeout,
        retries=args.retries,
        fail_fast=args.fail_fast,
        strict=args.strict,
    )
    try:
        execution = run_suite(options)
    except BackendUnavailable as exc:
        print(f"BACKEND UNAVAILABLE: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except (KeyError, ValueError, FileNotFoundError) as exc:
        print(f"CONFIG ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    run = execution.run
    if run.total == 0:
        print("CONFIG ERROR: no cases matched the selection", file=sys.stderr)
        return EXIT_CONFIG

    out_dir = args.report_dir / run.run_id
    _write_reports(args, execution, out_dir)

    print(console_reporter.render(run, colour=not args.no_color))
    print(f"  reports: {out_dir}\n")
    return EXIT_OK if run.ok else EXIT_FAILURE


def cmd_differential(args: argparse.Namespace) -> int:
    from .runners.differential_runner import run_differential

    options = RunOptions(
        base_url=args.candidate_url,
        suite=args.suite,
        case_ids=args.case,
        tags=args.tag,
        seed=args.seed,
        workers=1,
        timeout=args.timeout,
        retries=args.retries,
        strict=args.strict,
    )
    try:
        execution = run_differential(args.reference_url, args.candidate_url, options)
    except BackendUnavailable as exc:
        print(f"BACKEND UNAVAILABLE: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except (KeyError, ValueError) as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if execution.compared_cases == 0:
        print("CONFIG ERROR: no differential cases matched the selection", file=sys.stderr)
        return EXIT_CONFIG

    out_dir = args.report_dir / f"differential-{args.suite}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "divergences.json").write_text(
        json.dumps(execution.report_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nDifferential: reference={execution.reference_url} candidate={execution.candidate_url}")
    print(f"  cases compared          {execution.compared_cases}")
    print(f"  materially identical    {execution.identical_cases}")
    if execution.candidate_run:
        print(
            f"  candidate normal run    {'PASS' if execution.candidate_run.ok else 'FAIL'} "
            f"({execution.candidate_run.passed}/{execution.candidate_run.total} cases passed)"
        )
        if execution.candidate_run.blocker_failures:
            print(f"  candidate blockers      {len(execution.candidate_run.blocker_failures)}")
        if execution.candidate_run.threshold_failures:
            names = ", ".join(metric.name for metric in execution.candidate_run.threshold_failures)
            print(f"  candidate thresholds    {names}")
        if execution.candidate_normal_failures:
            print(f"  candidate critical checks {len(execution.candidate_normal_failures)}")
    for kind, count in sorted(execution.counts.items()):
        print(f"  {kind:<32} {count}")
    if execution.regressions:
        print(f"\n  Candidate regressions ({len(execution.regressions)}):")
        for divergence in execution.regressions[:20]:
            print(
                f"    - {divergence.case_id} turn {divergence.turn_index} {divergence.field}: "
                f"reference={divergence.reference!r} candidate={divergence.candidate!r}"
            )
    print(f"\n  report: {out_dir / 'divergences.json'}")
    print(
        "\n  Reminder: backend_lite is a reference, not legal ground truth. A divergence "
        "classified as reference_limitation or requires_human_review is a question, not a verdict.\n"
    )
    return EXIT_OK if execution.ok else EXIT_FAILURE


def cmd_load(args: argparse.Namespace) -> int:
    from .runners.load_runner import load_threshold_failures, run_load

    concurrency = args.concurrency
    different_chat_requests = args.requests
    same_chat_requests = args.same_chat_requests
    expected_http_statuses = (200,)
    profile = args.profile or "custom"
    if args.profile:
        try:
            definition = LoadConfig.load().profiles[args.profile]
        except KeyError:
            print(f"CONFIG ERROR: unknown load profile {args.profile!r}", file=sys.stderr)
            return EXIT_CONFIG
        except (OSError, ValueError) as exc:
            print(f"CONFIG ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return EXIT_CONFIG
        concurrency = definition.concurrency
        different_chat_requests = definition.different_chat_requests
        same_chat_requests = definition.same_chat_requests
        expected_http_statuses = tuple(definition.expected_http_statuses)

    if concurrency < 1 or different_chat_requests < 1 or same_chat_requests < 2:
        print(
            "CONFIG ERROR: load concurrency/requests must be positive and "
            "same-chat requests must be at least 2",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    try:
        thresholds = ThresholdsConfig.load()
    except (OSError, ValueError) as exc:
        print(f"CONFIG ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        results = run_load(
            args.base_url,
            concurrency,
            different_chat_requests,
            args.timeout,
            profile,
            same_chat_requests=same_chat_requests,
            expected_http_statuses=expected_http_statuses,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"BACKEND UNAVAILABLE: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE

    out_dir = args.report_dir / f"load-{profile}"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = [result.to_dict() for result in results]
    (out_dir / "load.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    failed = False
    threshold_failures = load_threshold_failures(results, thresholds)
    print(f"\nLoad — profile '{profile}' against {args.base_url}")
    for result in results:
        percentiles = result.percentiles()
        print(
            f"\n  scenario: {result.scenario} "
            f"(concurrency {result.concurrency}, {result.request_count} requests"
            + (f", {result.requests} planned" if result.request_count != result.requests else "")
            + ")"
        )
        print(f"    throughput   {result.throughput_rps:.1f} req/s")
        print(f"    p50 / p95    {percentiles.get('p50_ms', 0):.0f}ms / {percentiles.get('p95_ms', 0):.0f}ms")
        print(f"    p99 / max    {percentiles.get('p99_ms', 0):.0f}ms / {percentiles.get('max_ms', 0):.0f}ms")
        print(f"    error rate   {result.error_rate:.2%}")
        print(f"    timeouts     {result.timeout_rate:.2%}")
        print(f"    statuses     {dict(result.statuses)}")
        print(
            "    errors       "
            f"transport={result.transport_errors}, timeout={result.timeouts}, "
            f"http={result.http_errors}, invalid={result.invalid_responses}"
        )
        if result.scenario == "same_chat":
            if not result.ordering_checked:
                detail = f": {result.ordering_error}" if result.ordering_error else ""
                print(f"    ordering     NOT VERIFIED{detail}")
                failed = True
            elif result.ordering_violations:
                print(f"    ordering     VIOLATED ({result.ordering_violations}) — same-chat writes interleave")
                failed = True
            else:
                print("    ordering     intact")

        for failure in (item for item in threshold_failures if item.scenario == result.scenario):
            print(
                f"    threshold    FAIL {failure.metric}: "
                f"{failure.value:.2%} > {failure.threshold:.2%}"
            )
            failed = True

    print(f"\n  report: {out_dir / 'load.json'}\n")
    return EXIT_FAILURE if failed else EXIT_OK


def cmd_faults(args: argparse.Namespace) -> int:
    from .runners.fault_runner import run_faults, run_slow_response

    outcomes = run_faults(timeout=args.timeout)
    outcomes.append(run_slow_response(timeout=1.0))

    missed = [o for o in outcomes if not o.detected]
    print("\nEvaluator self-test — does the harness notice a broken backend?\n")
    for outcome in outcomes:
        mark = "DETECTED" if outcome.detected else "MISSED  "
        print(f"  {mark}  {outcome.scenario:<32} expected check: {outcome.expected_check}")
        if not outcome.detected:
            print(f"            observed failures: {outcome.observed_failures or 'NONE — the harness passed a broken response'}")

    out_dir = args.report_dir / "faults"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "faults.json").write_text(
        json.dumps([o.__dict__ for o in outcomes], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  {len(outcomes) - len(missed)}/{len(outcomes)} fault scenarios detected")
    print(f"  report: {out_dir / 'faults.json'}\n")
    if missed:
        print(f"  FAIL: the harness did not detect {len(missed)} injected defect(s).\n", file=sys.stderr)
        return EXIT_FAILURE
    return EXIT_OK


def cmd_coverage(_args: argparse.Namespace) -> int:
    inventory = coverage.legal_coverage()
    requirements = coverage.load_requirements()
    print("\nLegal coverage inventory (evaluation/config/legal_coverage.yaml)\n")
    domains = inventory.get("domains", {})
    print(f"  {'domain':<20} {'sources':>7}  {'oracle':<9} human review")
    for name, data in domains.items():
        print(
            f"  {name:<20} {data.get('source_count', 0):>7}  "
            f"{str(data.get('automated_oracle')):<9} {data.get('human_review_required')}"
        )
    print("\n  Explicitly unsupported:")
    for item in inventory.get("explicitly_unsupported", []):
        print(f"    - {item}")
    print("\n  Claim limits:")
    for item in inventory.get("claim_limits", []):
        print(f"    - {item}")
    print(f"\n  Requirement catalogue: {len(requirements)} entries\n")
    return EXIT_OK


COMMANDS = {
    "validate": cmd_validate,
    "run": cmd_run,
    "differential": cmd_differential,
    "load": cmd_load,
    "faults": cmd_faults,
    "coverage": cmd_coverage,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
