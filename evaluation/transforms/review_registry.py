"""Human review metadata for generated metamorphic cases.

The generator remains complete. This registry only decides whether a generated
case is suitable for an MVP gate; unreviewed and quarantined variants remain in
full/nightly diagnostic output.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

ReviewStatus = Literal["reviewed", "unreviewed", "quarantined"]
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "metamorphic_review.yaml"


@dataclass(frozen=True)
class ReviewEntry:
    review_status: ReviewStatus
    gate_eligible: bool
    reason: str = ""


@dataclass(frozen=True)
class ReviewRegistry:
    default: ReviewEntry
    cases: dict[str, ReviewEntry]

    def entry_for(self, case_id: str) -> ReviewEntry:
        return self.cases.get(case_id, self.default)


def _entry(raw: object, *, context: str) -> ReviewEntry:
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be a mapping")
    status = raw.get("review_status", "unreviewed")
    if status not in {"reviewed", "unreviewed", "quarantined"}:
        raise ValueError(f"{context}.review_status is invalid: {status!r}")
    eligible = raw.get("gate_eligible", False)
    if not isinstance(eligible, bool):
        raise ValueError(f"{context}.gate_eligible must be boolean")
    if eligible and status != "reviewed":
        raise ValueError(f"{context}: only reviewed cases may be gate eligible")
    reason = raw.get("reason", "")
    if not isinstance(reason, str):
        raise ValueError(f"{context}.reason must be a string")
    return ReviewEntry(status, eligible, reason)


@lru_cache(maxsize=1)
def load_review_registry(path: Path = REGISTRY_PATH) -> ReviewRegistry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("metamorphic review registry must be a mapping")
    default = _entry(raw.get("defaults", {}), context="defaults")
    case_rows = raw.get("cases", {})
    if not isinstance(case_rows, dict):
        raise ValueError("metamorphic review registry cases must be a mapping")
    cases = {str(case_id): _entry(row, context=f"cases.{case_id}") for case_id, row in case_rows.items()}
    return ReviewRegistry(default=default, cases=cases)


def normalized_question_key(text: str) -> str:
    """Fold accents/case/punctuation so equivalent noise is deduplicated."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", without_marks).strip()


def review_tags(case_id: str) -> list[str]:
    entry = load_review_registry().entry_for(case_id)
    tags = [f"review:{entry.review_status}"]
    if entry.gate_eligible:
        tags.append("gate_eligible")
    else:
        tags.append("diagnostic_only")
    return tags


__all__ = [
    "REGISTRY_PATH",
    "ReviewEntry",
    "ReviewRegistry",
    "load_review_registry",
    "normalized_question_key",
    "review_tags",
]
