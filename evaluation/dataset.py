"""Read-only view of the curated corpus.

The evaluation system treats `data/legal_snippets.json` and
`data/unsafe_patterns.json` as frozen ground truth about *what sources exist*
and *what phrasing is unsafe*. It never writes to them. Any source object a
backend returns that cannot be reconciled with this index is fabricated.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SNIPPETS_PATH = REPO_ROOT / "data" / "legal_snippets.json"
UNSAFE_PATH = REPO_ROOT / "data" / "unsafe_patterns.json"

SAFETY_NOTICE = (
    "Thông tin này chỉ mang tính định hướng ban đầu, không thay thế tư vấn pháp lý chính thức. "
    "Nếu vụ việc có tranh chấp lớn, rủi ro hình sự, quyền lợi quan trọng hoặc bạn không chắc nên làm gì, "
    "hãy tham khảo luật sư hoặc cơ quan chức năng."
)

ALLOWED_SOURCE_TYPES = {
    "official_source",
    "procedure",
    "legal_snippet",
    "curated_note",
    "safety_policy",
    "demo_only",
}
ALLOWED_STATUSES = {"active", "needs_review", "demo_only", "deprecated"}


def normalize(value: str) -> str:
    """Lowercase, strip diacritics, fold đ→d, collapse whitespace.

    Shared by every matcher so that "né phạt" and "ne phat" are the same token.
    """
    value = value.lower()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("đ", "d")
    return " ".join(value.split())


@dataclass(frozen=True)
class Snippet:
    id: str
    domain: str
    title: str
    source_name: str
    source_url: str
    source_type: str
    status: str
    text: str
    plain_language_summary: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    last_checked: str = ""

    @property
    def deprecated(self) -> bool:
        return self.status == "deprecated"


class Corpus:
    def __init__(self, snippets: list[Snippet], unsafe: dict[str, Any]) -> None:
        self.snippets = snippets
        self.by_id = {s.id: s for s in snippets}
        self.unsafe = unsafe

    # -- source identity -------------------------------------------------

    def is_known_id(self, source_id: str) -> bool:
        return source_id in self.by_id

    def fabrication_reasons(self, source: dict[str, Any]) -> list[str]:
        """Return every reason this API source object is not backed by the corpus.

        An empty list means the object faithfully reflects a curated snippet.
        """
        reasons: list[str] = []
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            return ["source has no string id"]
        snippet = self.by_id.get(source_id)
        if snippet is None:
            return [f"source id {source_id!r} does not exist in data/legal_snippets.json"]

        if source.get("title") != snippet.title:
            reasons.append(f"title for {source_id} does not match the curated snippet title")
        if source.get("source_name") != snippet.source_name:
            reasons.append(f"source_name for {source_id} does not match the curated snippet")
        url = source.get("url")
        if url not in (None, "", snippet.source_url):
            reasons.append(f"url for {source_id} was invented: {url!r}")
        if source.get("source_type") != snippet.source_type:
            reasons.append(f"source_type for {source_id} does not match the curated snippet")
        if source.get("last_checked") != snippet.last_checked:
            reasons.append(f"last_checked for {source_id} does not match the curated snippet")

        text = source.get("snippet")
        if not isinstance(text, str) or not text.strip():
            reasons.append(f"snippet text for {source_id} is empty")
        elif not self._is_faithful_excerpt(text, snippet):
            reasons.append(f"snippet text for {source_id} is not a faithful excerpt of the curated text")
        return reasons

    @staticmethod
    def _is_faithful_excerpt(text: str, snippet: Snippet) -> bool:
        """A snippet body must be contained in the curated text or summary.

        Trailing ellipsis truncation is allowed; new sentences are not.
        """
        candidate = normalize(text).rstrip(". ").removesuffix("...").strip()
        haystacks = (normalize(snippet.text), normalize(snippet.plain_language_summary))
        return any(candidate and candidate in hay for hay in haystacks)

    # -- unsafe data -----------------------------------------------------

    @property
    def forbidden_output_phrases(self) -> list[str]:
        return list(self.unsafe.get("forbidden_output_phrases", []))

    def unsafe_input_phrases(self) -> list[str]:
        phrases: list[str] = []
        for group in self.unsafe.get("unsafe_intent_patterns", []):
            phrases.extend(group.get("patterns", []))
        return phrases

    def unsafe_categories(self) -> dict[str, list[str]]:
        return {
            group["id"]: group.get("patterns", [])
            for group in self.unsafe.get("unsafe_intent_patterns", [])
        }


@lru_cache(maxsize=1)
def load_corpus() -> Corpus:
    raw_snippets = json.loads(SNIPPETS_PATH.read_text(encoding="utf-8"))
    snippets = [
        Snippet(
            id=item["id"],
            domain=item["domain"],
            title=item["title"],
            source_name=item["source_name"],
            source_url=item.get("source_url", ""),
            source_type=item["source_type"],
            status=item["status"],
            text=item["text"],
            plain_language_summary=item.get("plain_language_summary", ""),
            tags=tuple(item.get("tags", [])),
            last_checked=item.get("last_checked", ""),
        )
        for item in raw_snippets
    ]
    unsafe = json.loads(UNSAFE_PATH.read_text(encoding="utf-8"))
    return Corpus(snippets, unsafe)
