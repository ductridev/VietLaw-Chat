"""Regression coverage for semantic case validation and load accounting."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from evaluation.cli import EXIT_FAILURE, EXIT_OK, cmd_load
from evaluation.fakes.mutants import missing_assistant_message_id, valid_response
from evaluation.runners.load_runner import LoadResult, _analyze, load_threshold_failures
from evaluation.schemas.case import EvalCase, Expectation, Turn, load_cases_from_dir
from evaluation.schemas.config import LoadConfig, LoadProfile, ThresholdsConfig


def _case(*, turns: list[Turn], tags: list[str] | None = None) -> EvalCase:
    return EvalCase(
        id="schema_correction_001",
        title="schema correction",
        suite="conversation",
        requirement_ids=["CHAT-CONTEXT-001"],
        tags=tags or [],
        turns=turns,
    )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {"required_source_ids": ["civil_deposit_001"], "forbidden_source_ids": ["civil_deposit_001"]},
            "required_source_ids overlap forbidden_source_ids",
        ),
        (
            {"allowed_source_ids": ["civil_deposit_001"], "forbidden_source_ids": ["civil_deposit_001"]},
            "allowed_source_ids overlap forbidden_source_ids",
        ),
        ({"min_sources": -1}, "min_sources cannot be negative"),
        ({"max_sources": -1}, "max_sources cannot be negative"),
        ({"min_sources": 2, "max_sources": 1}, "min_sources cannot exceed max_sources"),
        ({"requires_sources": True, "max_sources": 0}, "requires_sources cannot be combined with max_sources=0"),
        (
            {"requires_no_sources": True, "allowed_source_ids": ["civil_deposit_001"]},
            "requires_no_sources cannot be combined",
        ),
        (
            {"required_source_ids": ["civil_deposit_001"], "allowed_source_ids": ["traffic_law_001"]},
            "required_source_ids must be included in allowed_source_ids",
        ),
        (
            {"required_source_ids": ["civil_deposit_001", "civil_rental_001"], "max_sources": 1},
            "max_sources is smaller than required_source_ids",
        ),
    ],
)
def test_source_requirement_contradictions_are_rejected(kwargs, message):
    with pytest.raises(ValidationError, match=message):
        Expectation(**kwargs)


def test_valid_source_constraints_are_preserved():
    expected = Expectation(
        requires_sources=True,
        min_sources=1,
        max_sources=2,
        required_source_ids=["civil_deposit_001"],
        allowed_source_ids=["civil_deposit_001", "civil_rental_001"],
        forbidden_source_ids=["traffic_law_001"],
    )
    assert expected.min_sources == 1
    assert expected.max_sources == 2


def test_first_turn_cannot_reuse_a_chat_id():
    with pytest.raises(ValidationError, match="first turn cannot reuse_chat_id"):
        _case(turns=[Turn(question="tiếp tục", reuse_chat_id=True)])


def test_first_turn_cannot_target_previous_chat_placeholder():
    with pytest.raises(ValidationError, match=r"first turn cannot target \$prev"):
        _case(turns=[Turn(op="chat_detail", chat_id="$prev")])


def test_reuse_chat_requires_same_session():
    with pytest.raises(ValidationError, match="reuse_chat_id requires session='same'"):
        _case(
            turns=[
                Turn(question="vụ việc ban đầu", session="fresh"),
                Turn(question="tiếp tục", session="fresh", reuse_chat_id=True),
            ]
        )


@pytest.mark.parametrize("op", ["analyze", "chat_detail", "chat_delete"])
def test_attacker_targeted_operation_requires_a_target_chat(op):
    kwargs = {"op": op, "session": "attacker"}
    if op == "analyze":
        kwargs["question"] = "xem cuộc trò chuyện"
    with pytest.raises(ValidationError, match="attacker operation requires a target chat"):
        _case(turns=[Turn(question="vụ việc ban đầu", session="fresh"), Turn(**kwargs)])


def test_attacker_chat_list_does_not_require_a_target_chat():
    case = _case(
        turns=[
            Turn(question="vụ việc ban đầu", session="fresh"),
            Turn(op="chat_list", session="attacker"),
        ]
    )
    assert case.turns[1].chat_id is None


def test_attacker_analyze_raw_body_can_carry_target_chat():
    case = _case(
        turns=[
            Turn(question="vụ việc ban đầu", session="fresh"),
            Turn(
                session="attacker",
                raw_body={"question": "xem lại", "chat_id": "chat_victim"},
            ),
        ]
    )
    assert case.turns[1].raw_body["chat_id"] == "chat_victim"


def test_empty_chat_id_is_rejected():
    with pytest.raises(ValidationError, match="chat_id cannot be empty"):
        Turn(op="chat_detail", chat_id="  ")


def test_multiturn_safety_tag_requires_per_turn_safety_class():
    with pytest.raises(ValidationError, match="multi-turn safety tag"):
        _case(
            tags=["unsafe_hard"],
            turns=[
                Turn(question="câu hỏi hợp pháp", session="fresh"),
                Turn(question="làm sao né phạt", reuse_chat_id=True),
            ],
        )


def test_multiturn_safety_tag_accepts_explicit_turn_class():
    case = _case(
        tags=["unsafe_hard"],
        turns=[
            Turn(question="câu hỏi hợp pháp", session="fresh"),
            Turn(
                question="làm sao né phạt",
                reuse_chat_id=True,
                expected=Expectation(safety_class="unsafe_hard"),
            ),
        ],
    )
    assert case.turns[1].expected.safety_class == "unsafe_hard"


def test_duplicate_case_ids_across_files_are_rejected(tmp_path):
    document = """
cases:
  - id: duplicate_001
    title: duplicate
    suite: semantic
    requirement_ids: [API-ANALYZE-001]
    question: legal question
"""
    (tmp_path / "a.yaml").write_text(document, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(document, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate case id"):
        load_cases_from_dir(tmp_path)


def _response(status: int, content: bytes, content_type: str = "application/json") -> httpx.Response:
    return httpx.Response(status, content=content, headers={"Content-Type": content_type})


async def _observe(
    response_or_error: httpx.Response | Exception,
    expected_http_statuses: tuple[int, ...] = (200,),
) -> LoadResult:
    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error

    result = LoadResult(
        profile="test",
        scenario="different_chats",
        concurrency=1,
        requests=1,
        expected_http_statuses=expected_http_statuses,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _analyze(
            client,
            "http://test",
            {"question": "q", "session_id": "s", "user_type": "citizen", "language": "vi"},
            result,
        )
    return result


@pytest.mark.parametrize("status", [400, 404, 429])
def test_load_4xx_counts_as_error(status):
    result = asyncio.run(_observe(_response(status, b'{}')))
    assert result.error_rate == 1.0
    assert result.http_errors == 1
    assert result.statuses[status] == 1
    assert load_threshold_failures([result], ThresholdsConfig.load())


@pytest.mark.parametrize("status", [500, 503])
def test_load_5xx_counts_as_error(status):
    result = asyncio.run(_observe(_response(status, b'{}')))
    assert result.error_rate == 1.0
    assert result.http_errors == 1
    assert result.statuses[status] == 1
    assert load_threshold_failures([result], ThresholdsConfig.load())


def test_load_expected_4xx_profile_does_not_count_as_error():
    result = asyncio.run(_observe(_response(404, b'{"error": {}}'), (404,)))
    assert result.error_rate == 0.0
    assert result.http_errors == 0


def test_load_timeout_counts_in_both_error_and_timeout_rates():
    request = httpx.Request("POST", "http://test/api/analyze")
    result = asyncio.run(_observe(httpx.ReadTimeout("slow", request=request)))
    assert result.error_rate == 1.0
    assert result.timeout_rate == 1.0
    assert result.timeouts == 1
    assert result.statuses["timeout"] == 1
    assert load_threshold_failures([result], ThresholdsConfig.load())


def test_load_invalid_json_counts_as_error():
    result = asyncio.run(_observe(_response(200, b"not-json", "text/plain")))
    assert result.error_rate == 1.0
    assert result.invalid_responses == 1
    assert result.statuses[200] == 1


def test_load_malformed_json_object_counts_as_invalid_response():
    result = asyncio.run(_observe(_response(200, b'{}')))
    assert result.error_rate == 1.0
    assert result.invalid_responses == 1


def test_load_missing_required_analyze_field_counts_as_invalid_response():
    body = missing_assistant_message_id(valid_response())
    result = asyncio.run(
        _observe(_response(200, json.dumps(body).encode("utf-8")))
    )
    assert result.error_rate == 1.0
    assert result.invalid_responses == 1
    assert load_threshold_failures([result], ThresholdsConfig.load())


def test_load_invalid_analyze_enum_counts_as_invalid_response():
    body = valid_response(domain="invented_domain")
    result = asyncio.run(_observe(_response(200, json.dumps(body).encode("utf-8"))))
    assert result.error_rate == 1.0
    assert result.invalid_responses == 1


def test_load_below_one_percent_threshold_passes():
    result = LoadResult(
        profile="test",
        scenario="different_chats",
        concurrency=1,
        requests=101,
        errors=1,
    )
    assert result.error_rate < 0.01
    assert load_threshold_failures([result], ThresholdsConfig.load()) == []


def test_load_error_and_timeout_thresholds_fail():
    result = LoadResult(
        profile="test",
        scenario="different_chats",
        concurrency=1,
        requests=100,
        errors=2,
        timeouts=2,
    )
    failures = load_threshold_failures([result], ThresholdsConfig.load())
    assert {failure.metric for failure in failures} == {
        "performance.error_rate_max",
        "performance.timeout_rate_max",
    }


def test_mvp_load_profile_reports_explicit_scenario_counts():
    mvp = LoadConfig.load().profiles["mvp"]
    assert mvp.different_chat_requests == 100
    assert mvp.same_chat_requests == 20


@pytest.mark.parametrize("statuses", [[200, 200], [99], [600]])
def test_load_profile_rejects_invalid_expected_statuses(statuses):
    with pytest.raises(ValidationError, match="expected_http_statuses"):
        LoadProfile(
            concurrency=1,
            different_chat_requests=2,
            same_chat_requests=2,
            expected_http_statuses=statuses,
        )


def _load_args(tmp_path):
    return SimpleNamespace(
        base_url="http://load.test",
        concurrency=1,
        requests=100,
        same_chat_requests=20,
        profile=None,
        timeout=1.0,
        report_dir=tmp_path,
    )


def test_load_cli_exits_one_when_error_threshold_is_exceeded(monkeypatch, tmp_path):
    from evaluation.runners import load_runner

    result = LoadResult(
        profile="custom",
        scenario="different_chats",
        concurrency=1,
        requests=100,
        statuses=Counter({500: 100}),
        errors=100,
        http_errors=100,
    )
    monkeypatch.setattr(load_runner, "run_load", lambda *_args, **_kwargs: [result])
    assert cmd_load(_load_args(tmp_path)) == EXIT_FAILURE


def test_load_cli_exits_zero_below_error_threshold(monkeypatch, tmp_path):
    from evaluation.runners import load_runner

    result = LoadResult(
        profile="custom",
        scenario="different_chats",
        concurrency=1,
        requests=101,
        statuses=Counter({200: 101}),
        errors=1,
        invalid_responses=1,
    )
    monkeypatch.setattr(load_runner, "run_load", lambda *_args, **_kwargs: [result])
    assert cmd_load(_load_args(tmp_path)) == EXIT_OK
