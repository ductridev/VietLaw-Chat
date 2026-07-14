"""API contract oracle: response shape, enums, error envelope, leak checks.

Every rule here traces to docs/api_contract.md. Contract violations are
blockers: a frontend cannot render an off-contract response.
"""

from __future__ import annotations

import re
from typing import Any

from ..dataset import ALLOWED_SOURCE_TYPES
from ..schemas.case import DECISIONS, DOMAINS, RISKS
from ..schemas.result import Check
from .base import TurnContext, make_check

ANALYZE_REQUIRED_FIELDS = (
    "contract_version",
    "request_id",
    "chat_id",
    "user_message_id",
    "assistant_message_id",
    "domain",
    "risk_level",
    "decision",
    "summary",
    "clarifying_questions",
    "checklist",
    "next_steps",
    "sources",
    "safety_notice",
    "confidence",
    "metadata",
)
CONFIDENCE_KEYS = {"domain", "risk", "answer"}
CONTENT_JSON_FIELDS = (
    "domain",
    "risk_level",
    "decision",
    "summary",
    "clarifying_questions",
    "checklist",
    "next_steps",
    "sources",
    "safety_notice",
    "confidence",
    "metadata",
)
SOURCE_REQUIRED_FIELDS = ("id", "title", "source_name", "snippet", "source_type", "last_checked")

TRACEBACK_MARKERS = (
    "traceback (most recent call last)",
    'file "/',
    "site-packages",
    "sqlalchemy",
    "sqlite3.operationalerror",
    "fastapi/applications.py",
    "raise ",
)
SECRET_MARKERS = ("api_key", "api-key", "authorization:", "sk-", "bearer ", "openai_api", "anthropic_api")


def _leak_checks(ctx: TurnContext) -> list[Check]:
    checks: list[Check] = []
    raw = ctx.response.raw_text.lower()
    if ctx.case.invariants.no_traceback_leak:
        hit = next((m for m in TRACEBACK_MARKERS if m in raw), None)
        checks.append(
            make_check(
                "no_traceback_leak",
                "contract",
                hit is None,
                f"response body leaks internals ({hit!r})",
                severity="blocker",
                metric="contract.traceback_leak",
            )
        )
    if ctx.case.invariants.no_secret_leak:
        hit = next((m for m in SECRET_MARKERS if m in raw), None)
        checks.append(
            make_check(
                "no_secret_leak",
                "contract",
                hit is None,
                f"response body may leak a secret ({hit!r})",
                severity="blocker",
                metric="contract.secret_leak",
            )
        )
    return checks


def _error_envelope_checks(ctx: TurnContext, expected_code: str | None) -> list[Check]:
    body = ctx.body
    checks = [
        make_check(
            "error_envelope_shape",
            "contract",
            isinstance(body.get("error"), dict)
            and isinstance(body["error"].get("code"), str)
            and isinstance(body["error"].get("message"), str)
            and body.get("contract_version") == "v1"
            and isinstance(body.get("request_id"), str),
            f"error response does not follow the error envelope: {ctx.response.raw_text[:200]}",
            severity="blocker",
        ),
        make_check(
            "error_safety_notice",
            "contract",
            isinstance(body.get("safety_notice"), str) and bool(body.get("safety_notice")),
            "error response is missing safety_notice",
            severity="blocker",
        ),
    ]
    if expected_code:
        actual = (body.get("error") or {}).get("code")
        checks.append(
            make_check(
                "error_code",
                "contract",
                actual == expected_code,
                f"expected error code {expected_code!r}, got {actual!r}",
                severity="blocker",
            )
        )
    return checks


def _analyze_success_checks(ctx: TurnContext) -> list[Check]:
    body = ctx.body
    checks: list[Check] = []

    missing = [f for f in ANALYZE_REQUIRED_FIELDS if f not in body]
    checks.append(
        make_check(
            "analyze_required_fields",
            "contract",
            not missing,
            f"response is missing required fields: {missing}",
            severity="blocker",
            metric="contract.schema_valid",
        )
    )
    checks.append(
        make_check(
            "contract_version",
            "contract",
            body.get("contract_version") == "v1",
            f"contract_version must be 'v1', got {body.get('contract_version')!r}",
            severity="blocker",
        )
    )

    for field, allowed in (("domain", DOMAINS), ("risk_level", RISKS), ("decision", DECISIONS)):
        checks.append(
            make_check(
                f"enum_{field}",
                "contract",
                body.get(field) in allowed,
                f"{field}={body.get(field)!r} is not a supported value",
                severity="blocker",
                metric="contract.schema_valid",
            )
        )

    for field in ("chat_id", "user_message_id", "assistant_message_id", "request_id"):
        value = body.get(field)
        checks.append(
            make_check(
                f"id_{field}",
                "contract",
                isinstance(value, str) and bool(value),
                f"{field} must be a non-null non-empty string, got {value!r}",
                severity="blocker",
            )
        )

    for field in ("clarifying_questions", "checklist", "next_steps", "sources"):
        value = body.get(field)
        checks.append(
            make_check(
                f"array_{field}",
                "contract",
                isinstance(value, list),
                f"{field} must be an array, got {type(value).__name__}",
                severity="blocker",
            )
        )
    checks.append(
        make_check(
            "summary_is_text",
            "contract",
            isinstance(body.get("summary"), str) and bool(body.get("summary", "").strip()),
            "summary must be a non-empty string",
            severity="blocker",
        )
    )

    confidence = body.get("confidence")
    checks.append(
        make_check(
            "confidence_keys",
            "contract",
            isinstance(confidence, dict) and set(confidence) == CONFIDENCE_KEYS,
            f"confidence must have exactly {sorted(CONFIDENCE_KEYS)}, got "
            f"{sorted(confidence) if isinstance(confidence, dict) else confidence!r}",
            severity="blocker",
        )
    )
    if isinstance(confidence, dict):
        bad = {k: v for k, v in confidence.items() if not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0}
        checks.append(
            make_check(
                "confidence_range",
                "contract",
                not bad,
                f"confidence values must be numbers in [0,1]: {bad}",
                severity="major",
            )
        )
    checks.append(
        make_check(
            "metadata_is_object",
            "contract",
            isinstance(body.get("metadata"), dict),
            "metadata must be an object",
            severity="blocker",
        )
    )

    checks.extend(_source_shape_checks(body.get("sources")))
    return checks


def _source_shape_checks(sources: Any) -> list[Check]:
    if not isinstance(sources, list):
        return []
    checks: list[Check] = []
    for i, source in enumerate(sources):
        if not isinstance(source, dict):
            checks.append(
                make_check(f"source_{i}_shape", "contract", False, "source is not an object", severity="blocker")
            )
            continue
        missing = [f for f in SOURCE_REQUIRED_FIELDS if not source.get(f)]
        checks.append(
            make_check(
                f"source_{i}_fields",
                "contract",
                not missing,
                f"source {source.get('id')!r} is missing fields {missing}",
                severity="blocker",
            )
        )
        checks.append(
            make_check(
                f"source_{i}_type",
                "contract",
                source.get("source_type") in ALLOWED_SOURCE_TYPES,
                f"source_type {source.get('source_type')!r} is not allowed",
                severity="blocker",
            )
        )
        last_checked = source.get("last_checked")
        checks.append(
            make_check(
                f"source_{i}_last_checked",
                "contract",
                isinstance(last_checked, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_checked or "")),
                f"last_checked {last_checked!r} is not YYYY-MM-DD",
                severity="major",
            )
        )
    return checks


def _health_checks(ctx: TurnContext) -> list[Check]:
    body = ctx.body
    checks = [
        make_check(
            "health_status",
            "contract",
            body.get("status") in {"ok", "degraded"},
            f"health status {body.get('status')!r} is not ok/degraded",
            severity="blocker",
        ),
        make_check(
            "health_contract_version",
            "contract",
            body.get("contract_version") == "v1",
            "health must report contract_version v1",
            severity="blocker",
        ),
    ]
    for flag in ("rag_loaded", "safety_loaded", "chat_store_ready"):
        checks.append(
            make_check(
                f"health_{flag}",
                "contract",
                isinstance(body.get(flag), bool),
                f"health.{flag} must be a boolean, got {body.get(flag)!r}",
                severity="blocker",
            )
        )
    checks.append(
        make_check(
            "health_service",
            "contract",
            isinstance(body.get("service"), str) and bool(body.get("service")),
            "health must report a service name",
            severity="minor",
        )
    )
    return checks


def _chat_detail_checks(ctx: TurnContext) -> list[Check]:
    body = ctx.body
    messages = body.get("messages")
    checks = [
        make_check(
            "chat_detail_messages",
            "contract",
            isinstance(messages, list),
            "chat detail must return a messages array",
            severity="blocker",
        )
    ]
    if not isinstance(messages, list):
        return checks

    required = ("message_id", "chat_id", "role", "content_type", "created_at")
    for i, message in enumerate(messages):
        if not isinstance(message, dict):
            checks.append(make_check(f"message_{i}_shape", "contract", False, "message is not an object", "blocker"))
            continue
        missing = [f for f in required if f not in message] + [
            f for f in ("content_text", "content_json") if f not in message
        ]
        checks.append(
            make_check(
                f"message_{i}_fields",
                "contract",
                not missing,
                f"message {i} is missing fields {missing}",
                severity="blocker",
            )
        )
        role, content_type = message.get("role"), message.get("content_type")
        if role == "user":
            checks.append(
                make_check(
                    f"message_{i}_user_text",
                    "contract",
                    content_type == "text" and isinstance(message.get("content_text"), str),
                    "user messages must be content_type=text with content_text",
                    severity="blocker",
                )
            )
        elif role == "assistant":
            content_json = message.get("content_json")
            checks.append(
                make_check(
                    f"message_{i}_assistant_structured",
                    "contract",
                    content_type == "structured" and isinstance(content_json, dict),
                    "assistant messages must be content_type=structured with an object content_json",
                    severity="blocker",
                )
            )
            if isinstance(content_json, dict):
                missing_content = [f for f in CONTENT_JSON_FIELDS if f not in content_json]
                checks.append(
                    make_check(
                        f"message_{i}_content_json_fields",
                        "contract",
                        not missing_content,
                        f"assistant content_json is missing {missing_content}",
                        severity="blocker",
                    )
                )
        else:
            checks.append(
                make_check(f"message_{i}_role", "contract", False, f"unknown role {role!r}", severity="blocker")
            )

    ordering = [(m.get("created_at", ""), m.get("message_id", "")) for m in messages if isinstance(m, dict)]
    checks.append(
        make_check(
            "message_ordering",
            "contract",
            ordering == sorted(ordering),
            "messages must be sorted by created_at then message_id",
            severity="blocker",
            metric="conversation.ordering",
        )
    )
    return checks


def evaluate(ctx: TurnContext) -> list[Check]:
    expectation = ctx.expectation
    checks: list[Check] = []

    if ctx.response.transport_error is not None:
        return [
            make_check(
                "transport",
                "contract",
                False,
                f"request failed: {ctx.response.transport_error}",
                severity="blocker",
            )
        ]

    if expectation.http_status is not None:
        checks.append(
            make_check(
                "http_status",
                "contract",
                ctx.response.status == expectation.http_status,
                f"expected HTTP {expectation.http_status}, got {ctx.response.status} "
                f"({ctx.response.raw_text[:160]})",
                severity="blocker",
            )
        )

    checks.append(
        make_check(
            "response_is_json",
            "contract",
            ctx.response.is_json,
            f"response body is not JSON: {ctx.response.raw_text[:120]!r}",
            severity="blocker",
        )
    )
    checks.extend(_leak_checks(ctx))
    if not ctx.response.is_json:
        return checks

    status = ctx.response.status or 0
    if status >= 400:
        checks.extend(_error_envelope_checks(ctx, expectation.error_code))
        return checks

    if ctx.turn.op == "analyze":
        checks.extend(_analyze_success_checks(ctx))
    elif ctx.turn.op == "health":
        checks.extend(_health_checks(ctx))
    elif ctx.turn.op == "chat_detail":
        checks.extend(_chat_detail_checks(ctx))
    elif ctx.turn.op == "chat_list":
        chats = ctx.body.get("chats")
        checks.append(
            make_check(
                "chat_list_shape",
                "contract",
                isinstance(chats, list) and ctx.body.get("contract_version") == "v1",
                "chat list must return contract_version v1 and a chats array",
                severity="blocker",
            )
        )
    elif ctx.turn.op == "chat_create":
        checks.append(
            make_check(
                "chat_create_shape",
                "contract",
                isinstance(ctx.body.get("chat_id"), str) and bool(ctx.body.get("chat_id")),
                "chat create must return a chat_id",
                severity="blocker",
            )
        )
    elif ctx.turn.op == "chat_delete":
        checks.append(
            make_check(
                "chat_delete_shape",
                "contract",
                ctx.body.get("deleted") is True and isinstance(ctx.body.get("chat_id"), str),
                "chat delete must return deleted=true and chat_id",
                severity="blocker",
            )
        )

    if expectation.expected_metadata:
        metadata = ctx.body.get("metadata")
        for key, expected in expectation.expected_metadata.items():
            actual = metadata.get(key) if isinstance(metadata, dict) else None
            allowed = expected if isinstance(expected, list) else [expected]
            checks.append(
                make_check(
                    f"metadata_{key}",
                    "contract",
                    actual in allowed,
                    f"metadata.{key}={actual!r} is not in {allowed!r}",
                    severity="major",
                )
            )
    return checks
