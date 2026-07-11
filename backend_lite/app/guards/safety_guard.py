from __future__ import annotations

import unicodedata

from ..runtime.agent_state import AgentState
from ..schemas.content import GeneratedContent
from ..schemas.state import GuardResult


class LiteSafetyGuard:
    _risk_rank = {"low": 0, "medium": 1, "high": 2}
    _negation_cues = (
        "khong the huong dan",
        "khong huong dan",
        "khong ho tro",
        "khong duoc",
        "khong nen",
        "tu choi",
    )
    _unsafe_output_patterns = {
        "legal_evasion": ("ne phat", "tron phat", "lach luat", "doi pho cong an"),
        "evidence_hiding": ("giau chung cu", "xoa chung cu", "tieu huy chung cu", "phi tang"),
        "fake_documents": ("lam gia giay to", "giay to gia", "gia chu ky", "lam gia hop dong"),
        "misreporting": ("khai gian", "noi doi co quan chuc nang", "noi doi cong an"),
    }

    @staticmethod
    def _normalize(value: str) -> str:
        lowered = unicodedata.normalize("NFD", value.lower())
        accentless = "".join(ch for ch in lowered if unicodedata.category(ch) != "Mn")
        return " ".join(accentless.replace("đ", "d").split())

    def _actionable_output_categories(self, content: GeneratedContent) -> list[str]:
        text = self._normalize(
            ".\n".join([content.summary, *content.clarifying_questions, *content.checklist, *content.next_steps])
        )
        categories: list[str] = []
        for category, patterns in self._unsafe_output_patterns.items():
            for pattern in patterns:
                start = 0
                while True:
                    index = text.find(pattern, start)
                    if index < 0:
                        break
                    context = text[max(0, index - 80):index]
                    boundary = max(context.rfind(mark) for mark in (".", "!", "?", ";"))
                    current_clause = context[boundary + 1:]
                    if not any(cue in current_clause for cue in self._negation_cues):
                        categories.append(category)
                        break
                    start = index + len(pattern)
                if category in categories:
                    break
        return categories

    @staticmethod
    def _safe_refusal(state: AgentState) -> GeneratedContent:
        safety_ids = {
            source.id
            for source in state.retrieval.retrieved_source_objects
            if source.source_type == "safety_policy"
        }
        valid_safety_ids = [
            source_id
            for source_id in (state.guard.final_content or state.generation.generated_content).used_source_ids
            if source_id in safety_ids
        ]
        return GeneratedContent(
            summary="Tôi không thể hỗ trợ nội dung hướng dẫn né tránh pháp luật hoặc che giấu, làm sai lệch thông tin.",
            clarifying_questions=[],
            checklist=[],
            next_steps=[
                "Hãy giữ nguyên tài liệu hợp pháp và chọn phương án khiếu nại, thực hiện thủ tục hoặc hỏi cơ quan có thẩm quyền.",
                "Nếu vụ việc có rủi ro cao, nên sớm trao đổi với luật sư.",
            ],
            used_source_ids=valid_safety_ids,
        )

    def apply(self, state: AgentState) -> GuardResult:
        content = state.guard.final_content or state.generation.generated_content
        if content is None:
            raise ValueError("generated content is missing")
        domain = state.classification.domain
        risk = state.classification.risk_level
        decision = state.classification.decision
        triggered = state.guard.guard_triggered
        flags = list(dict.fromkeys(state.classification.safety_flags))

        output_categories = self._actionable_output_categories(content)
        if output_categories:
            content = self._safe_refusal(state)
            domain = "high_risk"
            risk = "high"
            decision = "refuse_unsafe_request"
            triggered = True
            flags.extend(["generated_unsafe_output", *output_categories])

        if state.classification.unsafe_intent_detected or state.classification.high_risk_detected:
            domain = "high_risk"
            if self._risk_rank[risk] < self._risk_rank["high"]:
                triggered = True
            risk = "high"
            if state.classification.unsafe_intent_detected and decision not in {
                "refuse_unsafe_request", "recommend_professional_help"
            }:
                decision = "refuse_unsafe_request"
                triggered = True
            elif not state.classification.unsafe_intent_detected:
                decision = "recommend_professional_help"

        flags = list(dict.fromkeys(flags))
        state.guard.safety_guard_applied = True
        state.guard.guard_triggered = triggered
        return GuardResult(content, domain, risk, decision, flags, triggered)
