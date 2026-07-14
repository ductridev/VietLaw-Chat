"""Conversation, persistence and session-isolation oracle.

Covers what a single response body cannot show on its own: whether the turn
landed in the right chat, whether it survived a reload byte-for-byte, and
whether another session could see any of it.
"""

from __future__ import annotations

from typing import Any

from ..schemas.result import Check
from .base import TurnContext, make_check

CONTENT_FIELDS = (
    "domain",
    "risk_level",
    "decision",
    "summary",
    "clarifying_questions",
    "checklist",
    "next_steps",
    "sources",
    "safety_notice",
)


def _chat_continuity_checks(ctx: TurnContext) -> list[Check]:
    checks: list[Check] = []
    body = ctx.body
    chat_id = body.get("chat_id")

    if ctx.turn.reuse_chat_id and ctx.expected_chat_id:
        checks.append(
            make_check(
                "followup_same_chat",
                "conversation",
                chat_id == ctx.expected_chat_id,
                f"follow-up landed in chat {chat_id!r} instead of {ctx.expected_chat_id!r}",
                severity="blocker",
                metric="conversation.followup_consistency",
            )
        )
    if ctx.expectation.requires_new_chat and ctx.first_chat_id:
        checks.append(
            make_check(
                "new_chat_is_fresh",
                "conversation",
                chat_id != ctx.first_chat_id,
                f"a new chat must not reuse the previous chat_id {chat_id!r}",
                severity="blocker",
                metric="conversation.new_chat",
            )
        )
    return checks


def _session_leak_checks(ctx: TurnContext) -> list[Check]:
    """An attacker turn must never observe another session's data.

    Listing is the exception that proves the rule: an attacker's own list is a
    legitimate HTTP 200. What must never appear in it is the victim's chat_id.
    Every other cross-session operation must be refused outright.
    """
    if ctx.turn.session != "attacker" or not ctx.case.invariants.no_cross_session_leak:
        return []

    status = ctx.response.status or 0
    owner_chat_id = ctx.request_payload.get("_owner_chat_id")
    checks: list[Check] = []

    if ctx.turn.op == "chat_list":
        exposed = bool(owner_chat_id) and str(owner_chat_id) in ctx.response.raw_text
        checks.append(
            make_check(
                "no_cross_session_leak",
                "conversation",
                not exposed,
                f"another session's chat {owner_chat_id!r} appeared in this session's chat list",
                severity="blocker",
                metric="session.cross_session_leak",
            )
        )
    else:
        checks.append(
            make_check(
                "no_cross_session_leak",
                "conversation",
                status >= 400,
                f"cross-session access returned HTTP {status}: another session's chat was exposed",
                severity="blocker",
                metric="session.cross_session_leak",
            )
        )

    owner_session = ctx.request_payload.get("_owner_session_id")
    if owner_session:
        checks.append(
            make_check(
                "no_owner_session_disclosure",
                "conversation",
                str(owner_session) not in ctx.response.raw_text,
                "the response reveals the owning session_id",
                severity="blocker",
                metric="session.owner_disclosure",
            )
        )
    return checks


def _persistence_checks(ctx: TurnContext) -> list[Check]:
    expectation = ctx.expectation
    if not (expectation.requires_persistence or expectation.requires_reload_equivalence):
        return []
    if ctx.reload_detail is None:
        return [
            make_check(
                "reload_performed",
                "conversation",
                False,
                "case requires persistence but the chat could not be reloaded",
                severity="blocker",
            )
        ]

    detail = ctx.reload_detail.json_body
    messages = detail.get("messages")
    if not isinstance(messages, list):
        return [
            make_check(
                "reload_messages",
                "conversation",
                False,
                f"chat reload did not return messages (HTTP {ctx.reload_detail.status})",
                severity="blocker",
                metric="conversation.reload_equivalence",
            )
        ]

    body = ctx.body
    checks: list[Check] = []

    user_id = body.get("user_message_id")
    assistant_id = body.get("assistant_message_id")
    stored_user = _find(messages, user_id)
    stored_assistant = _find(messages, assistant_id)

    checks.append(
        make_check(
            "user_message_persisted",
            "conversation",
            stored_user is not None
            and stored_user.get("role") == "user"
            and stored_user.get("content_text") == ctx.turn.question,
            f"user message {user_id!r} was not persisted with its original text",
            severity="blocker",
            metric="conversation.persistence",
        )
    )
    checks.append(
        make_check(
            "assistant_message_persisted",
            "conversation",
            stored_assistant is not None
            and stored_assistant.get("role") == "assistant"
            and stored_assistant.get("content_type") == "structured"
            and isinstance(stored_assistant.get("content_json"), dict),
            f"assistant message {assistant_id!r} was not persisted as a structured message",
            severity="blocker",
            metric="conversation.persistence",
        )
    )

    ids = [m.get("message_id") for m in messages if isinstance(m, dict)]
    checks.append(
        make_check(
            "unique_message_ids",
            "conversation",
            len(ids) == len(set(ids)),
            f"duplicate message ids in chat: {ids}",
            severity="blocker",
        )
    )

    if expectation.requires_reload_equivalence and isinstance(stored_assistant, dict):
        content = stored_assistant.get("content_json")
        if isinstance(content, dict):
            mismatched = [f for f in CONTENT_FIELDS if content.get(f) != body.get(f)]
            checks.append(
                make_check(
                    "reload_equivalence",
                    "conversation",
                    not mismatched,
                    f"reloaded assistant content differs from the live response in {mismatched}",
                    severity="blocker",
                    metric="conversation.reload_equivalence",
                )
            )
    return checks


def _find(messages: list[Any], message_id: Any) -> dict[str, Any] | None:
    for message in messages:
        if isinstance(message, dict) and message.get("message_id") == message_id:
            return message
    return None


def evaluate(ctx: TurnContext) -> list[Check]:
    checks = _session_leak_checks(ctx)
    if ctx.is_success_analyze:
        checks.extend(_chat_continuity_checks(ctx))
        checks.extend(_persistence_checks(ctx))
    return checks
