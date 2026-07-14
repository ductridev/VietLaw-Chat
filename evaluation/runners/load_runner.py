"""Concurrency and latency measurement using asyncio + httpx.

Reports separately for different-chat traffic and same-chat traffic. If a
backend does not serialise same-chat writes, message ordering can break under
concurrency — that is measured and reported, never assumed to pass.
"""

from __future__ import annotations

import asyncio
import json
import re
import statistics
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..dataset import ALLOWED_SOURCE_TYPES
from ..oracles.contract_oracle import (
    ANALYZE_REQUIRED_FIELDS,
    CONFIDENCE_KEYS,
    SOURCE_REQUIRED_FIELDS,
)
from ..schemas.case import DECISIONS, DOMAINS, RISKS
from ..schemas.config import ThresholdsConfig

QUESTIONS = [
    "Tôi thuê nhà, chủ nhà giữ tiền cọc 2 tháng không trả, tôi phải làm gì?",
    "Tôi bị phạt giao thông nhưng không hiểu lỗi ghi trong biên bản.",
    "Tôi muốn bán đồ ăn online ở quê thì cần giấy tờ gì?",
    "Bạn tôi vay tiền đến hạn không trả, tôi cần làm gì?",
    "Tôi cần chuẩn bị giấy tờ gì khi làm thủ tục ở xã?",
]


def _valid_analyze_response(body: dict[str, Any]) -> bool:
    """Validate the minimum complete v1 analyze shape used by load traffic."""

    if any(field not in body for field in ANALYZE_REQUIRED_FIELDS):
        return False
    if body.get("contract_version") != "v1":
        return False
    if body.get("domain") not in DOMAINS or body.get("risk_level") not in RISKS:
        return False
    if body.get("decision") not in DECISIONS:
        return False
    if any(
        not isinstance(body.get(field), str) or not body[field]
        for field in ("request_id", "chat_id", "user_message_id", "assistant_message_id")
    ):
        return False
    if not isinstance(body.get("summary"), str) or not body["summary"].strip():
        return False
    if any(not isinstance(body.get(field), list) for field in ("clarifying_questions", "checklist", "next_steps", "sources")):
        return False
    if not isinstance(body.get("safety_notice"), str) or not body["safety_notice"]:
        return False
    confidence = body.get("confidence")
    if not isinstance(confidence, dict) or set(confidence) != CONFIDENCE_KEYS:
        return False
    if any(
        type(value) not in (int, float) or not 0.0 <= float(value) <= 1.0
        for value in confidence.values()
    ):
        return False
    if not isinstance(body.get("metadata"), dict):
        return False
    for source in body["sources"]:
        if not isinstance(source, dict):
            return False
        if any(not source.get(field) for field in SOURCE_REQUIRED_FIELDS):
            return False
        if source.get("source_type") not in ALLOWED_SOURCE_TYPES:
            return False
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(source.get("last_checked", ""))):
            return False
    return True


@dataclass
class LoadResult:
    profile: str
    scenario: str
    concurrency: int
    requests: int
    latencies_ms: list[float] = field(default_factory=list)
    statuses: Counter[Any] = field(default_factory=Counter)
    expected_http_statuses: tuple[int, ...] = (200,)
    errors: int = 0
    timeouts: int = 0
    transport_errors: int = 0
    http_errors: int = 0
    invalid_responses: int = 0
    wall_seconds: float = 0.0
    ordering_violations: int = 0
    ordering_checked: bool = False
    ordering_error: str | None = None

    @property
    def error_rate(self) -> float:
        return self.errors / self.request_count if self.request_count else 1.0

    @property
    def request_count(self) -> int:
        """Exact analyze requests observed, falling back to the plan for synthetic results."""
        observed = sum(self.statuses.values())
        return observed if observed else self.requests

    @property
    def timeout_rate(self) -> float:
        return self.timeouts / self.request_count if self.request_count else 0.0

    @property
    def throughput_rps(self) -> float:
        return self.request_count / self.wall_seconds if self.wall_seconds else 0.0

    def percentiles(self) -> dict[str, float]:
        if not self.latencies_ms:
            return {}
        values = sorted(self.latencies_ms)

        def pct(q: float) -> float:
            idx = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
            return values[idx]

        return {
            "p50_ms": pct(0.5),
            "p95_ms": pct(0.95),
            "p99_ms": pct(0.99),
            "mean_ms": statistics.fmean(values),
            "max_ms": values[-1],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "scenario": self.scenario,
            "concurrency": self.concurrency,
            "requests": self.request_count,
            "planned_requests": self.requests,
            "throughput_rps": round(self.throughput_rps, 2),
            "error_rate": round(self.error_rate, 4),
            "timeout_rate": round(self.timeout_rate, 4),
            "status_distribution": {str(k): v for k, v in sorted(self.statuses.items(), key=lambda kv: str(kv[0]))},
            "error_distribution": {
                "transport": self.transport_errors,
                "timeout": self.timeouts,
                "unexpected_http_status": self.http_errors,
                "invalid_response": self.invalid_responses,
            },
            "latency": {k: round(v, 1) for k, v in self.percentiles().items()},
            "ordering_checked": self.ordering_checked,
            "ordering_violations": self.ordering_violations,
            "ordering_error": self.ordering_error,
            "wall_seconds": round(self.wall_seconds, 2),
        }


async def _analyze(
    client: httpx.AsyncClient,
    base_url: str,
    payload: dict[str, Any],
    result: LoadResult,
) -> dict[str, Any] | None:
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{base_url}/api/analyze",
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        result.latencies_ms.append((time.perf_counter() - started) * 1000)
        result.statuses[response.status_code] += 1
        if response.status_code not in result.expected_http_statuses:
            result.http_errors += 1
            result.errors += 1
            return None
        try:
            body = response.json()
        except ValueError:
            result.invalid_responses += 1
            result.errors += 1
            return None
        if not isinstance(body, dict):
            result.invalid_responses += 1
            result.errors += 1
            return None
        if response.status_code == 200 and not _valid_analyze_response(body):
            result.invalid_responses += 1
            result.errors += 1
            return None
        return body
    except httpx.TimeoutException:
        result.timeouts += 1
        result.errors += 1
        result.statuses["timeout"] += 1
    except httpx.HTTPError as exc:
        result.transport_errors += 1
        result.errors += 1
        result.statuses[type(exc).__name__] += 1
    return None


async def _run_different_chats(
    base_url: str,
    concurrency: int,
    requests: int,
    timeout: float,
    profile: str,
    expected_http_statuses: tuple[int, ...],
) -> LoadResult:
    result = LoadResult(
        profile=profile,
        scenario="different_chats",
        concurrency=concurrency,
        requests=requests,
        expected_http_statuses=expected_http_statuses,
    )
    semaphore = asyncio.Semaphore(concurrency)
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout) as client:

        async def one(i: int) -> None:
            async with semaphore:
                await _analyze(
                    client,
                    base_url,
                    {
                        "question": QUESTIONS[i % len(QUESTIONS)],
                        "user_type": "citizen",
                        "language": "vi",
                        "session_id": f"load-{uuid.uuid4().hex[:12]}",
                    },
                    result,
                )

        await asyncio.gather(*(one(i) for i in range(requests)))

    result.wall_seconds = time.perf_counter() - started
    return result


async def _run_same_chat(
    base_url: str,
    concurrency: int,
    requests: int,
    timeout: float,
    profile: str,
    expected_http_statuses: tuple[int, ...],
) -> LoadResult:
    """Fire concurrent follow-ups into one chat, then check the stored order."""
    result = LoadResult(
        profile=profile,
        scenario="same_chat",
        concurrency=concurrency,
        requests=requests,
        expected_http_statuses=expected_http_statuses,
    )
    session_id = f"load-same-{uuid.uuid4().hex[:12]}"
    started = time.perf_counter()

    async with httpx.AsyncClient(timeout=timeout) as client:
        first = await _analyze(
            client,
            base_url,
            {
                "question": QUESTIONS[0],
                "user_type": "citizen",
                "language": "vi",
                "session_id": session_id,
            },
            result,
        )
        chat_id = (first or {}).get("chat_id")
        if not chat_id:
            result.ordering_error = "initial analyze did not return a usable chat_id"
            result.wall_seconds = time.perf_counter() - started
            return result

        semaphore = asyncio.Semaphore(concurrency)

        async def one(i: int) -> None:
            async with semaphore:
                await _analyze(
                    client,
                    base_url,
                    {
                        "question": f"{QUESTIONS[(i + 1) % len(QUESTIONS)]} (lượt {i})",
                        "user_type": "citizen",
                        "language": "vi",
                        "session_id": session_id,
                        "chat_id": chat_id,
                    },
                    result,
                )

        await asyncio.gather(*(one(i) for i in range(requests - 1)))

        try:
            detail = await client.get(
                f"{base_url}/api/chats/{chat_id}", params={"session_id": session_id}
            )
        except httpx.HTTPError as exc:
            result.ordering_error = f"chat reload transport error: {type(exc).__name__}"
        else:
            if detail.status_code != 200:
                result.ordering_error = f"chat reload returned HTTP {detail.status_code}"
            else:
                try:
                    detail_body = detail.json()
                except ValueError:
                    result.ordering_error = "chat reload returned invalid JSON"
                else:
                    messages = detail_body.get("messages") if isinstance(detail_body, dict) else None
                    if not isinstance(messages, list) or not all(
                        isinstance(message, dict) for message in messages
                    ):
                        result.ordering_error = "chat reload did not return a valid messages array"
                    else:
                        result.ordering_checked = True
                        keys = [
                            (message.get("created_at", ""), message.get("message_id", ""))
                            for message in messages
                        ]
                        if keys != sorted(keys):
                            result.ordering_violations += 1
                        roles = [message.get("role") for message in messages]
                        # A well-formed transcript strictly alternates user/assistant.
                        for a, b in zip(roles, roles[1:]):
                            if a == b:
                                result.ordering_violations += 1

    result.wall_seconds = time.perf_counter() - started
    return result


def run_load(
    base_url: str,
    concurrency: int,
    requests: int,
    timeout: float = 30.0,
    profile: str = "custom",
    scenarios: tuple[str, ...] = ("different_chats", "same_chat"),
    same_chat_requests: int | None = None,
    expected_http_statuses: tuple[int, ...] = (200,),
) -> list[LoadResult]:
    """Run explicit per-scenario request plans.

    ``requests`` remains the different-chat count for CLI/backward compatibility.
    Named profiles pass an explicit ``same_chat_requests`` count; custom callers
    that omit it run the same number in both scenarios instead of being silently
    capped.
    """
    results: list[LoadResult] = []
    if "different_chats" in scenarios:
        results.append(
            asyncio.run(
                _run_different_chats(
                    base_url,
                    concurrency,
                    requests,
                    timeout,
                    profile,
                    expected_http_statuses,
                )
            )
        )
    if "same_chat" in scenarios:
        results.append(
            asyncio.run(
                _run_same_chat(
                    base_url,
                    concurrency,
                    same_chat_requests if same_chat_requests is not None else requests,
                    timeout,
                    profile,
                    expected_http_statuses,
                )
            )
        )
    return results


@dataclass(frozen=True)
class LoadThresholdFailure:
    scenario: str
    metric: str
    value: float
    threshold: float


def load_threshold_failures(
    results: list[LoadResult], thresholds: ThresholdsConfig
) -> list[LoadThresholdFailure]:
    """Return blocking load-threshold failures for stable CLI exit logic."""
    failures: list[LoadThresholdFailure] = []
    for result in results:
        for metric, value in (
            ("performance.error_rate_max", result.error_rate),
            ("performance.timeout_rate_max", result.timeout_rate),
        ):
            passed, definition = thresholds.check(metric, value)
            if definition is not None and definition.blocker and passed is False:
                failures.append(
                    LoadThresholdFailure(
                        scenario=result.scenario,
                        metric=metric,
                        value=value,
                        threshold=definition.value,
                    )
                )
    return failures
