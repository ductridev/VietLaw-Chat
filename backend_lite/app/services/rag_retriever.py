from __future__ import annotations

import re
from dataclasses import dataclass

from ..constants import RETRIEVAL_STRATEGY
from ..runtime.agent_state import AgentState
from ..schemas.state import RetrievalResult
from ..stores.snippet_store import JsonSnippetStore, SnippetRecord
from .input_normalizer import InputNormalizer


@dataclass
class ScoredSnippet:
    snippet: SnippetRecord
    content_score: float
    boost_score: float

    @property
    def total(self) -> float:
        return self.content_score + self.boost_score


class KeywordRagRetriever:
    _topic_source_ids = {
        "rental_deposit": {"civil_deposit_001", "civil_rental_001"},
        "rental_lockout": {"civil_rental_001", "civil_contract_001", "civil_contract_002"},
        "loan_dispute": {"civil_loan_001"},
        "consumer_purchase": {"civil_consumer_001"},
        "traffic_fine": {"traffic_law_001", "traffic_fine_001", "traffic_documents_001"},
        "traffic_documents": {"traffic_law_001", "traffic_fine_001", "traffic_documents_001"},
        "traffic_accident": {"traffic_accident_001"},
        "traffic_evasion": {"traffic_safety_001"},
        "food_business": {
            "business_registration_001", "business_registration_002", "business_registration_003",
            "business_food_001", "business_food_002", "business_checklist_001",
        },
        "business_registration": {
            "business_registration_001", "business_registration_002", "business_registration_003",
            "business_checklist_001",
        },
        "administrative_business": {
            "business_registration_001", "business_registration_002", "business_registration_003",
            "business_checklist_001",
        },
        "business_evasion": {"business_safety_001"},
        "evidence_hiding": {"high_risk_evidence_001"},
        "fake_documents": {"high_risk_fake_docs_001"},
        "police_tactical_evasion": {"high_risk_police_001"},
        "police_high_risk": {"high_risk_police_001"},
        "threat_or_violence": {"high_risk_threat_001"},
        "coercive_debt_collection": {"high_risk_debt_001"},
    }
    _topic_phrases = {
        "rental_deposit": (
            "tien coc", "khoan coc", "thue nha", "hop dong thue", "giu coc", "hoan coc",
            "hoan lai", "khong tra coc", "khong hoan lai", "khong hoan tra",
        ),
        "rental_lockout": ("chu tro", "thue nha", "khoa cua"),
        "loan_dispute": (
            "cho vay", "vay tien", "no tien", "tra no", "tron no", "tranh mat", "doi no",
            "giay vay", "chuyen khoan",
        ),
        "consumer_purchase": ("mua hang", "don hang", "khong giao hang"),
        "traffic_fine": (
            "giao thong", "bien ban", "giay phat", "loi vi pham", "khong hieu loi", "xu phat",
        ),
        "traffic_documents": ("giay phep lai xe", "bang lai", "giay hen"),
        "traffic_accident": ("tai nan", "nguoi bi thuong"),
        "traffic_evasion": ("ne phat", "bi phat"),
        "food_business": (
            "ban do an", "do an online", "ban online", "facebook", "ban tai nha",
            "an toan thuc pham", "kinh doanh thuc pham", "ho kinh doanh", "dang ky kinh doanh",
        ),
        "business_registration": ("ho kinh doanh", "dang ky kinh doanh"),
        "administrative_business": ("dang ky kinh doanh", "ho kinh doanh"),
        "business_evasion": ("lach giay phep", "dang ky", "kinh doanh"),
        "evidence_hiding": ("chung cu",),
        "fake_documents": ("giay to gia", "lam gia"),
        "police_tactical_evasion": ("cong an", "hinh su"),
        "police_high_risk": ("cong an", "hinh su"),
        "threat_or_violence": ("de doa", "bao luc"),
        "coercive_debt_collection": ("doi no", "de doa"),
    }
    _stopwords = {
        "toi", "ban", "cua", "va", "la", "co", "can", "gi", "lam", "sao", "de", "mot",
        "nay", "do", "vay", "thi", "o", "tai", "cho", "duoc", "muon", "phai", "nhung",
        "khong", "the", "nao", "viec", "chuan", "bi",
    }
    _distinctive = {
        "coc", "thue", "vay", "no", "shop", "don", "hang", "phat", "giao", "thong", "bien",
        "lai", "kinh", "doanh", "thuc", "pham", "dang", "ky", "cong", "an", "chung", "cu",
        "gia", "de", "doa", "tai", "nan", "thuong",
    }
    _source_priority = {
        "official_source": 0.4,
        "procedure": 0.3,
        "legal_snippet": 0.2,
        "curated_note": 0.15,
        "safety_policy": 0.1,
        "demo_only": 0.0,
    }

    def __init__(self, store: JsonSnippetStore, normalizer: InputNormalizer, top_k: int = 3) -> None:
        self.store = store
        self.normalizer = normalizer
        self.top_k = top_k

    def _tokens(self, value: str) -> set[str]:
        _, accentless = self.normalizer.normalize(value.replace("_", " "))
        return {token for token in re.findall(r"[a-z0-9]+", accentless) if len(token) >= 2 and token not in self._stopwords}

    def _score(
        self,
        snippet: SnippetRecord,
        query: str,
        query_tokens: set[str],
        domain: str,
        topic: str | None,
    ) -> ScoredSnippet | None:
        searchable = " ".join(
            [snippet.title, snippet.source_name, snippet.text, snippet.plain_language_summary, *snippet.tags]
        )
        document_tokens = self._tokens(searchable)
        _, searchable_text = self.normalizer.normalize(searchable.replace("_", " "))
        anchors = self._topic_phrases.get(topic or "", ())
        anchor_gate = bool(anchors) and (
            any(anchor in query for anchor in anchors)
            and any(anchor in searchable_text for anchor in anchors)
        )
        if anchors and not anchor_gate:
            return None
        overlap = query_tokens & document_tokens
        tag_hits = 0
        for tag in snippet.tags:
            _, phrase = self.normalizer.normalize(tag.replace("_", " "))
            if phrase and phrase in query:
                tag_hits += 1
        distinctive_hits = len(overlap & self._distinctive)
        if tag_hits == 0 and distinctive_hits == 0 and not anchor_gate:
            return None
        content_score = len(overlap) + tag_hits * 3 + distinctive_hits * 0.75 + (2.0 if anchor_gate else 0.0)
        boost = self._source_priority.get(snippet.source_type, 0.0)
        if snippet.domain == domain or (domain == "high_risk" and snippet.domain == "high_risk"):
            boost += 1.0
        return ScoredSnippet(snippet, content_score, boost)

    @staticmethod
    def _domain_compatible(snippet: SnippetRecord, domain: str) -> bool:
        if domain == "high_risk":
            return snippet.domain == "high_risk"
        if domain == "administrative":
            return snippet.domain in {"administrative", "household_business"}
        return snippet.domain == domain

    @classmethod
    def _topic_compatible(cls, snippet: SnippetRecord, topic: str | None) -> bool:
        allowed_ids = cls._topic_source_ids.get(topic or "")
        return allowed_ids is None or snippet.id in allowed_ids

    @staticmethod
    def _safety_source_allowed(snippet: SnippetRecord, state: AgentState) -> bool:
        if snippet.source_type != "safety_policy":
            return True
        return state.classification.domain == "high_risk" or state.classification.decision in {
            "recommend_professional_help",
            "refuse_unsafe_request",
        }

    def retrieve(self, state: AgentState) -> RetrievalResult:
        self.store.ensure_ready()
        c = state.classification
        context = " ".join(state.chat.context_topic_terms)
        combined = " ".join(part for part in [c.accent_insensitive_question, context] if part).strip()
        if c.detected_language != "vi" or c.decision == "unsupported" or (c.domain == "unknown" and not context):
            return RetrievalResult(combined_query=combined, strategy=RETRIEVAL_STRATEGY)
        query_tokens = self._tokens(combined)
        scored = [
            result
            for snippet in self.store.active_snippets()
            if self._domain_compatible(snippet, c.domain)
            and self._topic_compatible(snippet, c.detected_topic)
            and self._safety_source_allowed(snippet, state)
            and (result := self._score(snippet, combined, query_tokens, c.domain, c.detected_topic)) is not None
        ]
        scored.sort(key=lambda item: (-item.total, item.snippet.id))
        selected = [item.snippet for item in scored[: self.top_k]]
        return RetrievalResult(
            sources=selected,
            source_objects=[item.as_source() for item in selected],
            combined_query=combined,
            strategy=RETRIEVAL_STRATEGY,
        )
