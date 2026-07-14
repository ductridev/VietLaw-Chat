"""Configuration schemas: suites, thresholds, environments, legal coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

Comparator = Literal["gte", "lte", "eq"]


class SuiteDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    include_suites: list[str] = Field(default_factory=list)
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    include_generated: bool = False
    explicit_case_ids: list[str] = Field(default_factory=list)
    generated_review_statuses: list[Literal["reviewed", "unreviewed", "quarantined"]] = Field(
        default_factory=list
    )
    require_gate_eligible: bool = False
    deduplicate_normalized_questions: bool = False
    required_seed: int | None = None
    """Optional content-review seed. A reviewed gate must not silently change text."""
    max_cases: int | None = None
    metamorphic_variants: int = 0
    """Variants generated per metamorphic base case (0 disables generation)."""


class SuitesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suites: dict[str, SuiteDef]

    @classmethod
    def load(cls, path: Path | None = None) -> SuitesConfig:
        path = path or CONFIG_DIR / "suites.yaml"
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class ThresholdDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    comparator: Comparator = "gte"
    description: str = ""
    blocker: bool = True
    """A blocker threshold fails the run. Non-blocker thresholds warn only."""


class ThresholdsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: dict[str, ThresholdDef]

    @classmethod
    def load(cls, path: Path | None = None) -> ThresholdsConfig:
        path = path or CONFIG_DIR / "thresholds.yaml"
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def check(self, name: str, value: float) -> tuple[bool | None, ThresholdDef | None]:
        definition = self.thresholds.get(name)
        if definition is None:
            return None, None
        if definition.comparator == "gte":
            return value >= definition.value, definition
        if definition.comparator == "lte":
            return value <= definition.value, definition
        return value == definition.value, definition


class EnvironmentDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    description: str = ""
    start_command: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    health_path: str = "/api/health"


class EnvironmentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environments: dict[str, EnvironmentDef]

    @classmethod
    def load(cls, path: Path | None = None) -> EnvironmentsConfig:
        path = path or CONFIG_DIR / "environments.yaml"
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


class LoadProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(gt=0)
    different_chat_requests: int = Field(gt=0)
    same_chat_requests: int = Field(gt=1)
    expected_http_statuses: list[int] = Field(default_factory=lambda: [200], min_length=1)
    description: str = ""
    mix: dict[str, float] = Field(default_factory=dict)

    @field_validator("expected_http_statuses")
    @classmethod
    def _valid_expected_statuses(cls, statuses: list[int]) -> list[int]:
        if len(statuses) != len(set(statuses)):
            raise ValueError("expected_http_statuses must not contain duplicates")
        if any(status < 100 or status > 599 for status in statuses):
            raise ValueError("expected_http_statuses must contain valid HTTP status codes")
        return statuses


class LoadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: dict[str, LoadProfile]

    @classmethod
    def load(cls, path: Path | None = None) -> LoadConfig:
        path = path or CONFIG_DIR / "load_profiles.yaml"
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
