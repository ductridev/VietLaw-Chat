from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from .config import Settings
from .guards.citation_guard import LiteCitationGuard
from .guards.safety_guard import LiteSafetyGuard
from .runtime.agent_runtime import AgentRuntime
from .services.chat_title import ChatTitleService
from .services.context_builder import SameChatContextBuilder
from .services.decision_policy import LiteDecisionPolicy
from .services.domain_classifier import LiteDomainClassifier
from .services.input_normalizer import InputNormalizer
from .services.language_detector import LiteLanguageDetector
from .services.lite_content_generator import LiteContentGenerator
from .services.rag_retriever import KeywordRagRetriever
from .services.response_builder import LiteResponseBuilder
from .services.risk_classifier import LiteRiskClassifier
from .services.unsafe_detector import PatternUnsafeDetector
from .stores.snippet_store import JsonSnippetStore
from .stores.sqlite_chat_store import SQLiteChatStore
from .stores.unsafe_pattern_store import JsonUnsafePatternStore


@dataclass
class AppContainer:
    settings: Settings
    chat_store: SQLiteChatStore
    snippet_store: JsonSnippetStore
    unsafe_store: JsonUnsafePatternStore
    runtime: AgentRuntime


def build_container(settings: Settings) -> AppContainer:
    chat_store = SQLiteChatStore(settings.chat_db_path)
    snippet_store = JsonSnippetStore(settings.legal_snippets_path)
    unsafe_store = JsonUnsafePatternStore(settings.unsafe_patterns_path)
    normalizer = InputNormalizer()
    runtime = AgentRuntime(
        chat_store=chat_store,
        context_builder=SameChatContextBuilder(chat_store, normalizer, settings.context_message_limit),
        normalizer=normalizer,
        language_detector=LiteLanguageDetector(),
        unsafe_detector=PatternUnsafeDetector(unsafe_store, normalizer),
        domain_classifier=LiteDomainClassifier(),
        risk_classifier=LiteRiskClassifier(),
        decision_policy=LiteDecisionPolicy(),
        retriever=KeywordRagRetriever(snippet_store, normalizer, settings.rag_top_k),
        content_generator=LiteContentGenerator(),
        citation_guard=LiteCitationGuard(),
        safety_guard=LiteSafetyGuard(),
        response_builder=LiteResponseBuilder(),
        title_service=ChatTitleService(),
    )
    return AppContainer(settings, chat_store, snippet_store, unsafe_store, runtime)


def get_container(request: Request) -> AppContainer:
    return request.app.state.container
