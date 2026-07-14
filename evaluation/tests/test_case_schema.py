"""Case schema validation. A loose schema is a silent oracle failure."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evaluation.runners.suite_runner import CASES_DIR
from evaluation.schemas.case import EvalCase, Expectation, Turn, load_cases_from_dir
from evaluation.schemas.config import SuitesConfig, ThresholdsConfig


def test_shorthand_question_expands_to_one_fresh_turn():
    case = EvalCase(
        id="x_001",
        title="t",
        suite="semantic",
        requirement_ids=["API-ANALYZE-001"],
        question="Chủ nhà giữ cọc.",
    )
    assert len(case.turns) == 1
    assert case.turns[0].session == "fresh"


def test_first_turn_is_always_fresh():
    case = EvalCase(
        id="x_002",
        title="t",
        suite="conversation",
        requirement_ids=["CHAT-CONTEXT-001"],
        turns=[Turn(question="a", session="same"), Turn(question="b", reuse_chat_id=True)],
    )
    assert case.turns[0].session == "fresh"


def test_requirement_ids_are_mandatory():
    with pytest.raises(ValidationError, match="requirement id"):
        EvalCase(id="x_003", title="t", suite="semantic", question="a b c")


def test_unknown_domain_is_rejected():
    with pytest.raises(ValidationError, match="unsupported values"):
        Expectation(acceptable_domain=["rental_law"])


def test_unknown_decision_is_rejected():
    with pytest.raises(ValidationError, match="unsupported values"):
        Expectation(acceptable_decision=["answer_definitively"])


def test_unknown_error_code_is_rejected():
    with pytest.raises(ValidationError, match="not an MVP error code"):
        Expectation(error_code="unsupported_language")


def test_contradictory_source_expectations_are_rejected():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        Expectation(requires_sources=True, requires_no_sources=True)


def test_requires_no_sources_cannot_require_a_source():
    with pytest.raises(ValidationError, match="cannot be combined"):
        Expectation(requires_no_sources=True, required_source_ids=["civil_deposit_001"])


def test_extra_field_is_rejected():
    """A typo in a case file must fail loudly, not be silently ignored."""
    with pytest.raises(ValidationError):
        EvalCase.model_validate(
            {
                "id": "x_004",
                "title": "t",
                "suite": "semantic",
                "requirement_ids": ["API-ANALYZE-001"],
                "question": "a b c",
                "expcted": {"http_status": 200},  # typo
            }
        )


def test_question_and_turns_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="not both"):
        EvalCase.model_validate(
            {
                "id": "x_005",
                "title": "t",
                "suite": "semantic",
                "requirement_ids": ["API-ANALYZE-001"],
                "question": "a b c",
                "turns": [{"question": "d e f"}],
            }
        )


def test_human_review_requires_a_reason():
    with pytest.raises(ValidationError, match="needs a reason"):
        EvalCase.model_validate(
            {
                "id": "x_006",
                "title": "t",
                "suite": "semantic",
                "requirement_ids": ["API-ANALYZE-001"],
                "question": "a b c",
                "human_review": {"required": True},
            }
        )


# -- the real corpus ------------------------------------------------------


def test_all_shipped_cases_validate():
    cases = load_cases_from_dir(CASES_DIR)
    assert len(cases) >= 100, f"expected a substantial case corpus, found {len(cases)}"


def test_case_ids_are_unique_and_sorted():
    ids = [c.id for c in load_cases_from_dir(CASES_DIR)]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids), "case ordering must be deterministic"


def test_every_case_cites_a_known_requirement():
    from evaluation.reporters.coverage import load_requirements

    catalogue = set(load_requirements())
    unknown = {
        rid
        for case in load_cases_from_dir(CASES_DIR)
        for rid in case.requirement_ids
        if rid not in catalogue
    }
    assert not unknown, f"cases cite requirement ids that do not exist: {sorted(unknown)}"


def test_blocker_cases_exist_in_every_critical_suite():
    cases = load_cases_from_dir(CASES_DIR)
    for suite in ("contract", "session", "safety", "rag", "conversation"):
        blockers = [c for c in cases if c.suite == suite and c.is_blocker]
        assert blockers, f"suite {suite} has no blocker case; it cannot gate anything"


def test_suites_and_thresholds_load():
    suites = SuitesConfig.load()
    thresholds = ThresholdsConfig.load()
    for name in ("smoke", "pr", "full", "nightly", "release"):
        assert name in suites.suites
    assert thresholds.thresholds["safety.hard_unsafe_recall"].value == 1.0
    assert thresholds.thresholds["rag.fabricated_source"].value == 0.0


def test_smoke_suite_is_small_and_broad():
    cases = [c for c in load_cases_from_dir(CASES_DIR) if "smoke" in c.tags]
    suites = {c.suite for c in cases}
    assert 8 <= len(cases) <= 25, f"smoke should stay small, found {len(cases)}"
    assert {"contract", "session", "safety", "conversation"} <= suites
