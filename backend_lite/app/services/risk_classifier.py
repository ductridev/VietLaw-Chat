from __future__ import annotations

from ..runtime.agent_state import AgentState
from ..schemas.content import RiskLevel


class LiteRiskClassifier:
    def classify(self, state: AgentState) -> RiskLevel:
        c = state.classification
        if c.detected_language != "vi":
            return "low"
        if c.unsafe_intent_detected or c.high_risk_detected or c.domain == "high_risk":
            return "high"
        if c.domain in {"civil_dispute", "traffic"}:
            return "medium"
        if c.domain in {"household_business", "administrative"}:
            return "low"
        return "medium" if c.detected_topic == "vague_legal" else "low"
