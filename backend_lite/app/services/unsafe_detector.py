from __future__ import annotations

from ..schemas.state import UnsafeDetection
from ..errors import AppError
from ..stores.unsafe_pattern_store import JsonUnsafePatternStore
from .input_normalizer import InputNormalizer


class PatternUnsafeDetector:
    def __init__(self, store: JsonUnsafePatternStore, normalizer: InputNormalizer) -> None:
        self.store = store
        self.normalizer = normalizer

    def _matches(self, question: str, pattern: str) -> bool:
        _, normalized_pattern = self.normalizer.normalize(pattern)
        return bool(normalized_pattern and normalized_pattern in question)

    def _topic(self, category: str, question: str) -> str:
        if category == "legal_evasion" and "giao thong" in question:
            return "traffic_evasion"
        return {
            "law_avoidance": "business_evasion",
            "business_fraud_or_misreporting": "business_evasion",
            "evidence_hiding": "evidence_hiding",
            "fake_documents": "fake_documents",
            "police_tactical_evasion": "police_tactical_evasion",
            "violent_or_coercive_debt_collection": "coercive_debt_collection",
            "police_or_criminal": "police_high_risk",
            "violence_or_threat": "threat_or_violence",
            "serious_traffic_accident": "traffic_accident",
            "land_or_property_dispute": "land_dispute",
            "large_money_dispute": "large_money_dispute",
            "non_legal_request": "unsupported_non_legal",
        }.get(category, category)

    def detect(self, accentless_question: str) -> UnsafeDetection:
        if not self.store.loaded:
            raise AppError("internal_error", "Safety policy tạm thời không khả dụng.", 500)
        if "khoi bi phat" in accentless_question:
            return UnsafeDetection(
                unsafe=True,
                high_risk=True,
                category="legal_evasion",
                detected_topic="traffic_evasion",
                expected_decision="refuse_unsafe_request",
                safety_flags=["legal_evasion", "traffic_evasion"],
                matched_patterns=["khỏi bị phạt"],
            )
        if "cong an" in accentless_question and "khong bi toi" in accentless_question and any(
            cue in accentless_question for cue in ("noi gi", "khai sao", "khai the nao")
        ):
            return UnsafeDetection(
                unsafe=True,
                high_risk=True,
                category="police_tactical_evasion",
                detected_topic="police_tactical_evasion",
                expected_decision="recommend_professional_help",
                safety_flags=["police_tactical_evasion"],
                matched_patterns=["nói gì để không bị tội"],
            )
        if any(phrase in accentless_question for phrase in ("bai tho", "ke chuyen cuoi", "xem tu vi")):
            return UnsafeDetection(
                category="non_legal_request",
                detected_topic="unsupported_non_legal",
                expected_decision="unsupported",
            )
        for group_name, unsafe, high_risk in (
            ("unsafe_intent_patterns", True, True),
            ("high_risk_patterns", False, True),
            ("unsupported_patterns", False, False),
        ):
            for item in self.store.groups(group_name):
                matches = [p for p in item.get("patterns", []) if self._matches(accentless_question, p)]
                if not matches:
                    continue
                category = str(item.get("category", "unknown"))
                expected = item.get("expected_decision")
                return UnsafeDetection(
                    unsafe=unsafe,
                    high_risk=high_risk,
                    category=category,
                    detected_topic=self._topic(category, accentless_question),
                    expected_decision=expected,
                    safety_flags=[category, *(["traffic_evasion"] if self._topic(category, accentless_question) == "traffic_evasion" else [])],
                    matched_patterns=matches,
                )
        return UnsafeDetection()
