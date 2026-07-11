from __future__ import annotations

from ..runtime.agent_state import AgentState
from ..schemas.content import Decision


class LiteDecisionPolicy:
    def choose(self, state: AgentState) -> Decision:
        c = state.classification
        if c.detected_language != "vi":
            return "unsupported"
        if c.unsafe_intent_detected:
            return c.decision if c.decision in {"recommend_professional_help", "refuse_unsafe_request"} else "refuse_unsafe_request"
        if c.high_risk_detected or c.domain == "high_risk":
            return "recommend_professional_help"
        if c.detected_topic == "unsupported_non_legal":
            return "unsupported"
        if c.domain == "unknown":
            return "ask_clarifying_questions"
        if state.chat.used_current_chat_history and c.detected_topic in {
            "rental_deposit", "loan_dispute", "consumer_purchase", "traffic_fine"
        }:
            return "answer_with_guidance"
        if c.domain in {"civil_dispute", "traffic"}:
            return "ask_clarifying_questions"
        if c.detected_topic == "food_business":
            return "ask_clarifying_questions"
        return "answer_with_guidance"
