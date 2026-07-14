"""Long-conversation generation and drift measurement.

Multi-turn cases in `cases/conversation/` cover the scripted scenarios. This
module builds the *long* conversation (10–20 turns) programmatically, because
writing twenty near-identical YAML turns by hand adds no signal.

What it measures: does the chat hold its domain across many turns, does message
ordering survive, and does latency grow as history accumulates.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas.case import EvalCase, Expectation, Turn

CIVIL_THREAD = [
    "Tôi thuê nhà, chủ nhà giữ tiền cọc 2 tháng không trả, tôi phải làm gì?",
    "Vậy tôi cần chuẩn bị giấy tờ gì?",
    "Hợp đồng thuê nhà của tôi chỉ viết tay thì có được không?",
    "Tôi có chứng từ chuyển khoản tiền cọc, như vậy đủ chưa?",
    "Chủ nhà nói tôi làm hỏng đồ nên giữ cọc, tôi nên làm gì?",
    "Tôi có nên gửi văn bản yêu cầu hoàn cọc không?",
    "Nếu chủ nhà vẫn không trả thì bước tiếp theo là gì?",
    "Tôi cần ghi lại timeline sự việc như thế nào?",
    "Tin nhắn Zalo có dùng làm bằng chứng được không?",
    "Số tiền cọc là 10 triệu, có đáng để nhờ luật sư không?",
    "Tôi có thể hỏi cơ quan nào ở địa phương?",
    "Thủ tục hòa giải thường mất bao lâu?",
    "Tôi nên chuẩn bị câu hỏi gì khi gặp luật sư?",
    "Nếu chủ nhà đã cho người khác thuê rồi thì sao?",
    "Tôi có cần giữ lại biên bản bàn giao nhà không?",
    "Tóm lại tôi nên làm gì trước tiên?",
]


@dataclass
class LongConversationSpec:
    turns: int = 12
    domain: str = "civil_dispute"


def build_long_conversation_case(spec: LongConversationSpec | None = None) -> EvalCase:
    spec = spec or LongConversationSpec()
    questions = CIVIL_THREAD[: max(2, min(spec.turns, len(CIVIL_THREAD)))]

    turns: list[Turn] = []
    for index, question in enumerate(questions):
        first = index == 0
        expectation = Expectation(
            http_status=200,
            acceptable_domain=[spec.domain],
            exact_safety_notice=True,
            max_latency_ms=15000,
        )
        if index == len(questions) - 1:
            # Only the final turn pays for a reload; every turn is still checked live.
            expectation.requires_persistence = True
        turns.append(
            Turn(
                question=question,
                session="fresh" if first else "same",
                reuse_chat_id=not first,
                expected=expectation,
            )
        )

    return EvalCase(
        id=f"conversation_long_{len(questions):02d}_turns",
        title=f"Long civil-dispute conversation ({len(questions)} turns)",
        suite="conversation",
        severity="major",
        requirement_ids=["API-ANALYZE-004", "CHAT-CONTEXT-001", "CHAT-STORE-002"],
        tags=["conversation", "long_thread", "drift"],
        turns=turns,
    )


def drift_report(case_result_domains: list[str]) -> dict[str, object]:
    """Summarise how often the domain moved across a long thread."""
    if not case_result_domains:
        return {"turns": 0, "domain_changes": 0, "stable": True}
    changes = sum(1 for a, b in zip(case_result_domains, case_result_domains[1:]) if a != b)
    return {
        "turns": len(case_result_domains),
        "domains": case_result_domains,
        "domain_changes": changes,
        "stable": changes == 0,
    }
