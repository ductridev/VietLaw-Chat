from __future__ import annotations

from typing import Any, Protocol

from ..schemas.api import AnalyzeResponse
from ..schemas.content import GeneratedContent
from ..schemas.state import CitationGuardResult


class ChatStore(Protocol):
    def create_chat(self, session_id: str, title: str = "Chat mới") -> Any: ...
    def get_chat(self, chat_id: str) -> Any | None: ...
    def get_chat_for_session(self, chat_id: str, session_id: str) -> Any | None: ...
    def add_message(self, message: Any) -> None: ...
    def list_messages(self, chat_id: str, limit: int | None = None) -> list[Any]: ...


class SnippetStore(Protocol):
    loaded: bool
    def ensure_ready(self) -> None: ...
    def active_snippets(self) -> list[Any]: ...


class UnsafePatternStore(Protocol):
    loaded: bool
    def groups(self, name: str) -> list[dict[str, Any]]: ...


class ContextBuilder(Protocol):
    def build(self, state: Any) -> None: ...


class LanguageDetector(Protocol):
    def detect(self, normalized: str, accentless: str, requested_language: str) -> str: ...


class UnsafeDetector(Protocol):
    def detect(self, accentless_question: str) -> Any: ...


class DomainClassifier(Protocol):
    def classify(self, state: Any) -> tuple[str, str | None]: ...


class RiskClassifier(Protocol):
    def classify(self, state: Any) -> str: ...


class DecisionPolicy(Protocol):
    def choose(self, state: Any) -> str: ...


class Retriever(Protocol):
    def retrieve(self, state: Any) -> Any: ...


class ContentGenerator(Protocol):
    model_name: str
    used_llm: bool
    async def generate(self, state: Any) -> GeneratedContent: ...


class CitationGuard(Protocol):
    def apply(self, state: Any) -> CitationGuardResult: ...


class SafetyGuard(Protocol):
    def apply(self, state: Any) -> Any: ...


class ResponseBuilder(Protocol):
    def build(self, state: Any) -> AnalyzeResponse: ...


class TitleService(Protocol):
    def make(self, question: str, topic: str | None = None) -> str: ...
