"""Fault-injection runner.

Runs a canonical analyze case against a deliberately broken backend and asserts
that the harness *notices*. A fault scenario "passes" when the expected check
fails — the opposite polarity of a normal suite, which is exactly the point:
this is how the evaluation system proves it is not blindly green.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..clients.api_client import ApiClient
from ..dataset import load_corpus
from ..fakes.fake_backend import FakeBackend
from ..fakes.mutants import MUTANTS
from ..schemas.case import EvalCase, Expectation, Turn

# scenario -> the check that must fail (None = harness must survive, no specific check)
TRANSPORT_SCENARIOS: dict[str, str] = {
    "connection_reset": "transport",
    "invalid_json": "response_is_json",
    "wrong_content_type": "response_is_json",
    "empty_body": "response_is_json",
    "missing_field": "analyze_required_fields",
    "http_500": "http_status",
    "http_503_retrieval_error": "http_status",
    "http_429": "http_status",
    "http_422_instead_of_400": "http_status",
}


@dataclass
class FaultOutcome:
    scenario: str
    expected_check: str
    detected: bool
    defect: str = ""
    observed_failures: list[str] = field(default_factory=list)


def _probe_case() -> EvalCase:
    return EvalCase(
        id="fault_probe_analyze",
        title="Fault probe: civil deposit analyze",
        suite="robustness",
        severity="blocker",
        requirement_ids=["API-ANALYZE-001"],
        tags=["fault_probe"],
        question="Tôi thuê nhà, chủ nhà giữ tiền cọc 2 tháng không trả, tôi phải làm gì?",
        expected=Expectation(
            http_status=200,
            acceptable_domain=["civil_dispute"],
            acceptable_risk=["medium"],
            acceptable_decision=["ask_clarifying_questions", "answer_with_guidance"],
            allowed_source_ids=["civil_deposit_001", "civil_rental_001", "civil_contract_001", "civil_contract_002"],
        ),
    )


def _run_scenario(scenario: str, expected_check: str, defect: str, timeout: float) -> FaultOutcome:
    from ..runners.case_runner import CaseRunner

    corpus = load_corpus()
    case = _probe_case()
    with FakeBackend(scenario=scenario) as backend:
        with ApiClient(backend.base_url, timeout=timeout, retries=0) as client:
            result = CaseRunner(client, corpus=corpus, run_id="fault").run(case).result

    observed = sorted({c.name.split("::")[0] for c in result.failed_checks})
    detected = any(c.name == expected_check or c.name.startswith(expected_check) for c in result.failed_checks)
    return FaultOutcome(
        scenario=scenario,
        expected_check=expected_check,
        detected=detected,
        defect=defect,
        observed_failures=observed,
    )


def run_faults(timeout: float = 3.0) -> list[FaultOutcome]:
    """Every fault scenario, plus every response mutant, through the real client."""
    outcomes: list[FaultOutcome] = []

    for scenario, expected_check in TRANSPORT_SCENARIOS.items():
        outcomes.append(_run_scenario(scenario, expected_check, f"transport/protocol fault: {scenario}", timeout))

    for scenario, (_mutator, expected_check, defect) in MUTANTS.items():
        outcomes.append(_run_scenario(scenario, expected_check, defect, timeout))

    return outcomes


def run_slow_response(timeout: float = 1.0) -> FaultOutcome:
    """A backend slower than the client timeout must surface as a transport failure."""
    from ..runners.case_runner import CaseRunner

    case = _probe_case()
    with FakeBackend(scenario="slow_response", delay_seconds=timeout + 2.0) as backend:
        with ApiClient(backend.base_url, timeout=timeout, retries=0) as client:
            result = CaseRunner(client, corpus=load_corpus(), run_id="fault").run(case).result
    failures = [c.name for c in result.failed_checks]
    return FaultOutcome(
        scenario="slow_response",
        expected_check="transport",
        detected="transport" in failures,
        defect="backend exceeds the client timeout",
        observed_failures=sorted(set(failures)),
    )
