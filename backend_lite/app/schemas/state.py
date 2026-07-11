from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .content import Decision, Domain, GeneratedContent, RiskLevel, SourceObject


@dataclass
class UnsafeDetection:
    unsafe: bool = False
    high_risk: bool = False
    category: str | None = None
    detected_topic: str | None = None
    expected_decision: Decision | None = None
    safety_flags: list[str] = field(default_factory=list)
    matched_patterns: list[str] = field(default_factory=list)


@dataclass
class GuardResult:
    content: GeneratedContent
    domain: Domain
    risk_level: RiskLevel
    decision: Decision
    safety_flags: list[str]
    guard_triggered: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class CitationGuardResult:
    content: GeneratedContent
    used_source_ids: list[str] = field(default_factory=list)
    removed_source_ids: list[str] = field(default_factory=list)
    unsupported_claims_detected: bool = False
    content_cautioned: bool = False
    guard_triggered: bool = False
    confidence_adjustment: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    sources: list[Any] = field(default_factory=list)
    source_objects: list[SourceObject] = field(default_factory=list)
    combined_query: str = ""
    strategy: str = ""
