from __future__ import annotations

from ..runtime.agent_state import AgentState
from ..schemas.state import CitationGuardResult


class LiteCitationGuard:
    _strong_claim_markers = (
        "chắc chắn",
        "theo luật",
        "bắt buộc",
        "đương nhiên",
        "trái pháp luật",
        "vi phạm pháp luật",
        "có quyền yêu cầu",
    )
    _cautious_summary = (
        "Tập dữ liệu MVP hiện chưa có nguồn đủ phù hợp để xác nhận chắc chắn. "
        "Bạn nên kiểm tra văn bản hoặc cơ quan có thẩm quyền trước khi hành động."
    )
    _cautious_next_step = (
        "Kiểm tra lại văn bản áp dụng hoặc hỏi cơ quan có thẩm quyền, luật sư trước khi hành động."
    )

    def apply(self, state: AgentState) -> CitationGuardResult:
        content = state.generation.generated_content
        if content is None:
            raise ValueError("generated content is missing")
        allowed = set(state.retrieval.retrieved_source_ids)
        valid = [source_id for source_id in content.used_source_ids if source_id in allowed]
        removed = [source_id for source_id in content.used_source_ids if source_id not in allowed]
        warnings: list[str] = []
        unsupported_claims = False
        content_cautioned = False
        confidence_adjustment: float | None = None
        guarded = content.model_copy(update={"used_source_ids": valid})

        if removed:
            warnings.append("citation_guard_removed_unknown_source_ids")
            confidence_adjustment = -0.2
            visible = " ".join([content.summary, *content.clarifying_questions, *content.checklist, *content.next_steps]).lower()
            unsupported_claims = not valid and any(marker in visible for marker in self._strong_claim_markers)
            if unsupported_claims:
                guarded = guarded.model_copy(
                    update={
                        "summary": self._cautious_summary,
                        "next_steps": [self._cautious_next_step],
                    }
                )
                content_cautioned = True
                warnings.append("citation_guard_cautioned_unsupported_claim")

        state.trace.warnings.extend(warning for warning in warnings if warning not in state.trace.warnings)
        state.guard.guard_triggered = state.guard.guard_triggered or bool(removed)
        state.guard.citation_guard_applied = True
        return CitationGuardResult(
            content=guarded,
            used_source_ids=valid,
            removed_source_ids=removed,
            unsupported_claims_detected=unsupported_claims,
            content_cautioned=content_cautioned,
            guard_triggered=bool(removed),
            confidence_adjustment=confidence_adjustment,
            warnings=warnings,
        )
