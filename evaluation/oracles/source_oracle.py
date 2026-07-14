"""RAG / citation-integrity oracle.

The central rule: every source object in a response must reconcile field-by-field
with a snippet in data/legal_snippets.json. A backend cannot pass this oracle by
returning a plausible-looking citation — id, title, source_name, url,
source_type, last_checked and snippet text must all match the curated record.

Relevance is judged against per-case source labels, never against `domain`
alone: a source from the right domain but the wrong topic is still irrelevant.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..dataset import normalize
from ..schemas.result import Check
from .base import TurnContext, make_check

SOURCE_ORACLE_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "source_oracle.yaml"


@dataclass(frozen=True)
class SourceOracleConfig:
    """Small, explicit configuration for the excerpt-usefulness heuristic."""

    min_excerpt_chars: int = 30
    min_excerpt_tokens: int = 5

    @classmethod
    def load(cls, path: Path = SOURCE_ORACLE_CONFIG_PATH) -> SourceOracleConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        source = raw.get("source", raw)
        if not isinstance(source, dict):
            raise ValueError("source oracle config must contain a mapping named 'source'")
        unknown = set(source) - {"min_excerpt_chars", "min_excerpt_tokens"}
        if unknown:
            raise ValueError(f"unknown source oracle settings: {sorted(unknown)}")
        values = {
            "min_excerpt_chars": source.get("min_excerpt_chars", cls.min_excerpt_chars),
            "min_excerpt_tokens": source.get("min_excerpt_tokens", cls.min_excerpt_tokens),
        }
        for name, value in values.items():
            if type(value) is not int or value < 1:  # bool is not a valid integer setting
                raise ValueError(f"{name} must be a positive integer")
        return cls(**values)


SOURCE_ORACLE_CONFIG = SourceOracleConfig.load()

STRONG_CLAIM_PHRASES = (
    "theo luat, ban chac chan",
    "chac chan thang",
    "chac chan dung",
    "chac chan sai",
    "chac chan co quyen",
    "chac chan duoc boi thuong",
    "quy dinh tai dieu",
    "can cu dieu",
    "theo nghi dinh",
    "theo thong tu",
    "phap luat quy dinh ro",
    "bat buoc phai hoan tien ngay",
    "duong nhien duoc boi thuong",
)


def _returned_sources(ctx: TurnContext) -> list[dict[str, Any]]:
    sources = ctx.body.get("sources")
    return [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else []


def _fabrication_checks(ctx: TurnContext, sources: list[dict[str, Any]]) -> list[Check]:
    checks: list[Check] = []
    if not ctx.case.invariants.no_fabricated_source:
        return checks
    reasons: list[str] = []
    for source in sources:
        reasons.extend(ctx.corpus.fabrication_reasons(source))
    checks.append(
        make_check(
            "no_fabricated_source",
            "source",
            not reasons,
            "fabricated source detected: " + "; ".join(reasons[:4]),
            severity="blocker",
            metric="rag.fabricated_source",
        )
    )
    if ctx.case.invariants.no_deprecated_source:
        deprecated = [
            s.get("id")
            for s in sources
            if (snippet := ctx.corpus.by_id.get(str(s.get("id")))) is not None and snippet.deprecated
        ]
        checks.append(
            make_check(
                "no_deprecated_source",
                "source",
                not deprecated,
                f"deprecated sources returned: {deprecated}",
                severity="blocker",
                metric="rag.deprecated_source",
            )
        )
    return checks


def _excerpt_measurement(text: Any) -> tuple[int, int]:
    """Return normalized alphanumeric characters and whitespace-delimited tokens."""

    if not isinstance(text, str):
        return 0, 0
    normalized = normalize(text).rstrip(". ")
    return sum(char.isalnum() for char in normalized), len(normalized.split())


def _excerpt_is_useful(text: Any, config: SourceOracleConfig = SOURCE_ORACLE_CONFIG) -> bool:
    chars, tokens = _excerpt_measurement(text)
    return chars >= config.min_excerpt_chars and tokens >= config.min_excerpt_tokens


def _excerpt_usefulness_checks(
    sources: list[dict[str, Any]],
    config: SourceOracleConfig = SOURCE_ORACLE_CONFIG,
) -> list[Check]:
    """Reject faithful but useless fragments without claiming legal support.

    Corpus reconciliation proves source identity.  This heuristic merely makes
    the displayed excerpt long enough to be meaningful; it does not establish
    that the cited text legally supports the generated answer.
    """

    if not sources:
        return []
    reasons: list[str] = []
    for source in sources:
        text = source.get("snippet")
        if _excerpt_is_useful(text, config):
            continue
        chars, tokens = _excerpt_measurement(text)
        reasons.append(
            f"{source.get('id')!r} has {chars} normalized chars/{tokens} tokens "
            f"(minimum {config.min_excerpt_chars}/{config.min_excerpt_tokens})"
        )
    return [
        make_check(
            "source_excerpt_useful",
            "source",
            not reasons,
            "source excerpt is too small to be useful: " + "; ".join(reasons[:4]),
            severity="major",
            metric="rag.source_usefulness",
        )
    ]


def _presence_checks(ctx: TurnContext, sources: list[dict[str, Any]]) -> list[Check]:
    expectation = ctx.expectation
    checks: list[Check] = []
    ids = [str(s.get("id")) for s in sources]

    if expectation.requires_sources:
        checks.append(
            make_check(
                "requires_sources",
                "source",
                bool(sources),
                "case requires at least one source but sources is empty",
                severity="major",
                metric="rag.source_presence",
            )
        )
    if expectation.requires_no_sources:
        checks.append(
            make_check(
                "requires_no_sources",
                "source",
                not sources,
                f"case requires no sources but got {ids}",
                severity="blocker",
                metric="rag.no_source_accuracy",
            )
        )
    if expectation.min_sources is not None:
        checks.append(
            make_check(
                "min_sources",
                "source",
                len(sources) >= expectation.min_sources,
                f"expected at least {expectation.min_sources} sources, got {len(sources)}",
                severity="major",
            )
        )
    if expectation.max_sources is not None:
        checks.append(
            make_check(
                "max_sources",
                "source",
                len(sources) <= expectation.max_sources,
                f"expected at most {expectation.max_sources} sources (top-k), got {len(sources)}",
                severity="major",
                metric="rag.top_k_respected",
            )
        )

    if expectation.required_source_ids:
        missing = [sid for sid in expectation.required_source_ids if sid not in ids]
        checks.append(
            make_check(
                "required_source_ids",
                "source",
                not missing,
                f"expected sources {missing} to be retrieved, got {ids}",
                severity="major",
                metric="rag.recall",
            )
        )
    if expectation.forbidden_source_ids:
        present = [sid for sid in expectation.forbidden_source_ids if sid in ids]
        checks.append(
            make_check(
                "forbidden_source_ids",
                "source",
                not present,
                f"forbidden sources returned: {present}",
                severity="blocker",
                metric="rag.irrelevant_source",
            )
        )
    return checks


def _relevance_checks(ctx: TurnContext, sources: list[dict[str, Any]]) -> list[Check]:
    """Label-based precision. Only runs when the case declares a label set."""
    expectation = ctx.expectation
    label_set = set(expectation.allowed_source_ids) | set(expectation.required_source_ids)
    if not label_set or not sources:
        return []
    ids = [str(s.get("id")) for s in sources]
    irrelevant = [sid for sid in ids if sid not in label_set]
    relevant_count = len(ids) - len(irrelevant)
    precision = relevant_count / len(ids)
    return [
        make_check(
            "source_relevance",
            "source",
            not irrelevant,
            f"irrelevant sources for this topic: {irrelevant} (labelled relevant: {sorted(label_set)})",
            severity="major",
            metric="rag.precision",
        ),
        Check(
            name="source_precision",
            oracle="source",
            status="pass",  # informational; the failure signal is source_relevance
            severity="minor",
            message=f"precision@{len(ids)}={precision:.2f}",
            metric="rag.precision_value",
        ),
    ]


def _no_source_caution_checks(ctx: TurnContext, sources: list[dict[str, Any]]) -> list[Check]:
    """With no sources, the answer must not assert legal authority."""
    if sources:
        return []
    from .base import find_outside_refusal, generated_text

    text = generated_text(ctx.body)
    hits = [p for p in STRONG_CLAIM_PHRASES if find_outside_refusal(text, p)]
    return [
        make_check(
            "no_source_caution",
            "source",
            not hits,
            f"response cites legal authority while returning zero sources: {hits}",
            severity="blocker",
            metric="rag.unsupported_claim",
        )
    ]


def evaluate(ctx: TurnContext) -> list[Check]:
    if not ctx.is_success_analyze:
        return []
    sources = _returned_sources(ctx)
    checks: list[Check] = []
    checks.extend(_fabrication_checks(ctx, sources))
    checks.extend(_excerpt_usefulness_checks(sources))
    checks.extend(_presence_checks(ctx, sources))
    checks.extend(_relevance_checks(ctx, sources))
    checks.extend(_no_source_caution_checks(ctx, sources))

    metadata = ctx.body.get("metadata")
    if isinstance(metadata, dict) and "has_sources" in metadata:
        checks.append(
            make_check(
                "metadata_has_sources_consistent",
                "source",
                bool(metadata.get("has_sources")) == bool(sources),
                f"metadata.has_sources={metadata.get('has_sources')!r} contradicts {len(sources)} sources",
                severity="major",
            )
        )
    if isinstance(metadata, dict) and isinstance(metadata.get("retrieval_count"), int):
        checks.append(
            make_check(
                "metadata_retrieval_count_consistent",
                "source",
                metadata["retrieval_count"] >= len(sources),
                f"metadata.retrieval_count={metadata['retrieval_count']} is below the "
                f"{len(sources)} cited sources, so a citation was not retrieved",
                severity="blocker",
                metric="rag.citation_integrity",
            )
        )
    return checks
