from __future__ import annotations

from typing import Any

import pytest

from evaluation.clients.api_client import ApiResponse
from evaluation.dataset import Corpus, load_corpus
from evaluation.fakes.mutants import valid_response
from evaluation.oracles.base import TurnContext
from evaluation.schemas.case import EvalCase, Expectation, Turn


@pytest.fixture(scope="session")
def corpus() -> Corpus:
    return load_corpus()


def make_response(body: Any, status: int = 200, latency_ms: float = 120.0) -> ApiResponse:
    import json

    raw = json.dumps(body, ensure_ascii=False) if body is not None else ""
    return ApiResponse(status=status, body=body, raw_text=raw, latency_ms=latency_ms)


def make_case(
    case_id: str = "test_case_001",
    suite: str = "semantic",
    severity: str = "blocker",
    tags: list[str] | None = None,
    question: str = "Tôi thuê nhà, chủ nhà giữ tiền cọc không trả.",
    expected: Expectation | None = None,
) -> EvalCase:
    return EvalCase(
        id=case_id,
        title="test case",
        suite=suite,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        requirement_ids=["API-ANALYZE-001"],
        tags=tags or [],
        question=question,
        expected=expected or Expectation(),
    )


def make_ctx(
    corpus: Corpus,
    body: Any = None,
    case: EvalCase | None = None,
    status: int = 200,
    reload_detail: ApiResponse | None = None,
    turn: Turn | None = None,
    request_payload: dict[str, Any] | None = None,
    latency_ms: float = 120.0,
) -> TurnContext:
    case = case or make_case()
    turn = turn or case.turns[0]
    body = valid_response() if body is None else body
    return TurnContext(
        case=case,
        turn=turn,
        index=1,
        response=make_response(body, status=status, latency_ms=latency_ms),
        corpus=corpus,
        expectation=turn.expected,
        reload_detail=reload_detail,
        request_payload=request_payload or {},
    )


@pytest.fixture
def ctx_factory(corpus: Corpus):
    def factory(**kwargs: Any) -> TurnContext:
        return make_ctx(corpus, **kwargs)

    return factory
