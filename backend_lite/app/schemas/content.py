from __future__ import annotations

from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

Domain: TypeAlias = Literal[
    "civil_dispute",
    "traffic",
    "household_business",
    "administrative",
    "high_risk",
    "unknown",
]
RiskLevel: TypeAlias = Literal["low", "medium", "high"]
Decision: TypeAlias = Literal[
    "answer_with_guidance",
    "ask_clarifying_questions",
    "recommend_professional_help",
    "refuse_unsafe_request",
    "unsupported",
]
SourceType: TypeAlias = Literal[
    "official_source",
    "procedure",
    "legal_snippet",
    "curated_note",
    "demo_only",
    "safety_policy",
]


class SourceObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    source_name: str
    url: str | None = None
    snippet: str
    source_type: SourceType
    last_checked: str


class Confidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)
    answer: float = Field(ge=0, le=1)


class GeneratedContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    clarifying_questions: list[str]
    checklist: list[str]
    next_steps: list[str]
    used_source_ids: list[str]


class AnalyzeContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Domain
    risk_level: RiskLevel
    decision: Decision
    summary: str
    clarifying_questions: list[str]
    checklist: list[str]
    next_steps: list[str]
    sources: list[SourceObject]
    safety_notice: str
    confidence: Confidence
    metadata: dict[str, Any]
