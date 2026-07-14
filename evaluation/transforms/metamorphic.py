"""Generate metamorphic variants from base cases.

Metamorphic relation: if a transform preserves meaning, then the backend's
domain must not change, its risk must not drop, an unsafe request must stay
refused, a safe request must stay unrefused, and grounding must not vanish just
because punctuation moved.

The generated case inherits the base case's expectations, so a variant that
flips a classification fails exactly like a curated case would.
"""

from __future__ import annotations

import random

from ..schemas.case import EvalCase, Expectation, Turn
from .paraphrase_templates import PARAPHRASES
from .review_registry import review_tags
from .vietnamese_noise import NOISE_TRANSFORMS

# Ordered so a given (case, index) always picks the same transform for a seed.
#
# `telex_fragment` is deliberately NOT in this set. It rewrites "tôi" as "tooi",
# which is IME *composition state*, not text a user submits. safety_policy.md §5
# defines the supported input space as Vietnamese with diacritics, without
# diacritics, any case, and any punctuation — Telex fragments are outside it, so
# a backend failing them is answering for unsupported input, not regressing.
# It stays in the transform library: enable it here if the product decides to
# support IME-fragment input, and it becomes a gate like everything else.
DEFAULT_TRANSFORMS = (
    "remove_accents",
    "lowercase_no_accent",
    "common_typos",
    "polite_wrap",
    "messy_punctuation",
    "extra_whitespace",
    "unicode_nfd",
    "strip_punctuation",
    "add_filler",
    "uppercase",
    "d_confusion",
    "noisy_lowercase",
)


def _relaxed(expectation: Expectation) -> Expectation:
    """Drop wording-level assertions that a noisy variant cannot be held to.

    Classification, source identity and safety must survive the transform.
    Exact phrase requirements must not: a backend is free to word a reply to a
    typo-laden question differently, and asserting otherwise would generate
    false failures that teach nothing.
    """
    data = expectation.model_dump()
    data["must_include"] = []
    data["must_match"] = []
    # must_not_include and forbidden ids are safety/grounding constraints: kept.
    return Expectation.model_validate(data)


def generate_variants(
    base: EvalCase,
    count: int,
    seed: int,
    transforms: tuple[str, ...] = DEFAULT_TRANSFORMS,
) -> list[EvalCase]:
    """Return `count` deterministic variants of a single-turn base case."""
    if len(base.turns) != 1 or not base.turns[0].question:
        return []

    question = base.turns[0].question
    expectation = _relaxed(base.turns[0].expected)
    group = base.metamorphic_group or base.id
    paraphrases = PARAPHRASES.get(group, [])

    variants: list[EvalCase] = []
    for i in range(count):
        rng = random.Random(f"{seed}:{base.id}:{i}")
        if i < len(paraphrases):
            variant_question = paraphrases[i]
            label = f"paraphrase_{i + 1}"
        else:
            name = transforms[(i - len(paraphrases)) % len(transforms)]
            variant_question = NOISE_TRANSFORMS[name](question, rng)
            label = name

        if variant_question.strip() == question.strip():
            continue

        variants.append(
            EvalCase(
                id=f"{base.id}__mm_{i + 1:02d}_{label}",
                title=f"{base.title} — {label.replace('_', ' ')}",
                suite="metamorphic",
                severity="major" if base.severity == "blocker" else base.severity,
                requirement_ids=base.requirement_ids,
                tags=[*base.tags, "metamorphic", f"mm:{label}", *review_tags(f"{base.id}__mm_{i + 1:02d}_{label}")],
                user_type=base.user_type,
                language=base.language,
                metamorphic_group=group,
                generated=True,
                invariants=base.invariants,
                turns=[
                    Turn(
                        question=variant_question,
                        session="fresh",
                        user_type=base.user_type,
                        language=base.language,
                        expected=expectation,
                    )
                ],
            )
        )
    return variants


def expand(cases: list[EvalCase], variants_per_case: int, seed: int) -> list[EvalCase]:
    """Expand every case tagged `metamorphic_base` into variants."""
    generated: list[EvalCase] = []
    for case in cases:
        if "metamorphic_base" not in case.tags:
            continue
        generated.extend(generate_variants(case, variants_per_case, seed))
    return generated
