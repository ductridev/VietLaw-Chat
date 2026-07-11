from __future__ import annotations

from ..runtime.agent_state import AgentState
from ..schemas.content import Domain


class LiteDomainClassifier:
    _rental_deposit_terms = (
        "tien coc", "khoan coc", "dat coc", "giu coc", "hoan coc", "khong tra coc",
        "hoan lai khoan coc", "khong hoan lai", "khong hoan tra", "thue nha", "hop dong thue",
    )
    _loan_terms = (
        "cho vay", "vay tien", "khong tra no", "no tien", "tron no", "tranh mat",
        "doi no", "giay vay", "chuyen khoan vay", "den han khong tra",
    )
    _traffic_fine_terms = (
        "phat giao thong", "bien ban giao thong", "bien ban", "giay phat", "khong hieu loi",
        "loi vi pham", "loi ghi trong bien ban", "bi xu phat", "bang lai xe",
    )
    _food_business_terms = (
        "ban do an", "do an online", "ban online", "ban qua facebook", "ban tai nha",
        "kinh doanh thuc pham", "an toan thuc pham",
    )

    def classify(self, state: AgentState) -> tuple[Domain, str | None]:
        c = state.classification
        if c.detected_language != "vi":
            return "unknown", "unsupported_language"
        if c.unsafe_intent_detected or c.high_risk_detected:
            return "high_risk", c.detected_topic
        if c.detected_topic == "unsupported_non_legal":
            return "unknown", "unsupported_non_legal"

        current = c.accent_insensitive_question
        context = " ".join(state.chat.context_topic_terms)
        text = f"{current} {context}".strip()

        if any(term in text for term in ("chu tro khoa cua", "khoa cua phong", "tai san ca nhan")):
            return "civil_dispute", "rental_lockout"
        if any(term in text for term in self._rental_deposit_terms):
            return "civil_dispute", "rental_deposit"
        if any(term in text for term in self._loan_terms):
            return "civil_dispute", "loan_dispute"
        if any(term in text for term in ("mua hang online", "khong giao hang", "don hang", "shop nhan tien")):
            return "civil_dispute", "consumer_purchase"
        if any(term in text for term in ("giu bang lai", "giu giay phep lai xe")):
            return "traffic", "traffic_documents"
        if any(term in text for term in self._traffic_fine_terms):
            return "traffic", "traffic_fine"
        if any(term in text for term in self._food_business_terms):
            return "household_business", "food_business"
        if any(term in text for term in ("mo ho kinh doanh", "dang ky ho kinh doanh", "ho kinh doanh nho")):
            return "household_business", "business_registration"
        if "dang ky kinh doanh" in text and any(term in text for term in ("thu tuc", "dia phuong", "ho so")):
            return "administrative", "administrative_business"
        if any(term in current for term in ("tranh chap hop dong", "hop dong")):
            return "civil_dispute", "civil_contract"
        return "unknown", "vague_legal" if "phap ly" in current else None
