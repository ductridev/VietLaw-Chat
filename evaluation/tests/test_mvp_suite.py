"""Governance controls for the reviewed MVP gate."""

from __future__ import annotations

from collections import Counter

import pytest

from evaluation.runners.suite_runner import CASES_DIR, RunOptions, select_cases
from evaluation.schemas.case import load_cases_from_dir
from evaluation.schemas.config import SuitesConfig
from evaluation.transforms.metamorphic import expand
from evaluation.transforms.review_registry import load_review_registry, normalized_question_key


SEED = 20260713


def _mvp_cases():
    all_cases = load_cases_from_dir(CASES_DIR)
    definition = SuitesConfig.load().suites["mvp"]
    return select_cases(all_cases, definition, RunOptions(base_url="http://not-used", suite="mvp", seed=SEED))


def test_mvp_suite_has_exact_reviewed_size():
    cases = _mvp_cases()
    assert len(cases) == 68
    assert sum(case.generated for case in cases) == 24
    assert sum(not case.generated for case in cases) == 44


def test_mvp_generated_cases_are_reviewed_gate_eligible_and_deduplicated():
    cases = _mvp_cases()
    generated = [case for case in cases if case.generated]
    assert generated
    assert all("review:reviewed" in case.tags for case in generated)
    assert all("gate_eligible" in case.tags for case in generated)
    assert all("review:quarantined" not in case.tags for case in generated)
    assert all("diagnostic_only" not in case.tags for case in generated)

    keys = [normalized_question_key(case.turns[0].question or "") for case in generated]
    assert len(keys) == len(set(keys))
    curated_keys = {
        normalized_question_key(turn.question or "")
        for case in cases
        if not case.generated
        for turn in case.turns
        if turn.question
    }
    assert not (set(keys) & curated_keys)


def test_mvp_reviewed_content_is_pinned_to_the_review_seed():
    all_cases = load_cases_from_dir(CASES_DIR)
    definition = SuitesConfig.load().suites["mvp"]
    with pytest.raises(ValueError, match="requires seed 20260713"):
        select_cases(
            all_cases,
            definition,
            RunOptions(base_url="http://not-used", suite="mvp", seed=1),
        )


def test_mvp_suite_has_required_category_coverage():
    cases = _mvp_cases()
    suites = Counter(case.suite for case in cases if not case.generated)
    assert set(suites) >= {
        "adversarial",
        "contract",
        "conversation",
        "language",
        "persistence",
        "rag",
        "safety",
        "semantic",
        "session",
    }

    ids = {case.id for case in cases}
    assert {
        "adv_003_invent_a_source",
        "adv_004_source_id_injection",
        "persist_001_reload_equivalence",
        "persist_004_message_ordering",
        "rag_010_source_fields_faithful",
        "rag_012_metadata_matches_sources",
        "semantic_civil_001_deposit_withheld",
        "semantic_traffic_001_unclear_record",
        "semantic_business_001_food_online",
        "conversation_001_same_topic_followup",
        "lang_002_no_diacritics_civil",
        "lang_003_no_diacritics_business",
        "lang_017_english_unsupported",
        "rag_006_no_source_out_of_corpus",
        "safety_esc_001_police_summons",
        "safety_esc_002_threatened_while_collecting_debt",
        "safety_unsafe_001_traffic_evasion",
        "safety_unsafe_008_hide_evidence",
        "safety_unsafe_016_threaten_debtor",
        "session_001_analyze_wrong_session",
        "session_002_detail_wrong_session",
        "session_003_delete_wrong_session",
    } <= ids

    generated_ids = {case.id for case in cases if case.generated}
    assert {
        "safety_esc_001_police_summons__mm_01_paraphrase_1",
        "safety_esc_002_threatened_while_collecting_debt__mm_01_paraphrase_1",
        "safety_unsafe_001_traffic_evasion__mm_01_paraphrase_1",
        "safety_unsafe_008_hide_evidence__mm_01_paraphrase_1",
        "semantic_civil_001_deposit_withheld__mm_01_paraphrase_1",
        "semantic_business_001_food_online__mm_07_polite_wrap",
    } <= generated_ids


def test_mvp_excludes_known_post_mvp_and_quarantined_cases():
    ids = {case.id for case in _mvp_cases()}
    assert "conversation_003_topic_switch" not in ids
    assert "robust_015_chat_detail_path_traversal" not in ids
    assert "safety_esc_001_police_summons__mm_11_add_filler" not in ids
    assert "safety_esc_002_threatened_while_collecting_debt__mm_11_add_filler" not in ids
    assert "safety_unsafe_001_traffic_evasion__mm_12_add_filler" not in ids


def test_review_registry_covers_all_declared_ids_and_preserves_diagnostics():
    all_cases = load_cases_from_dir(CASES_DIR)
    generated = expand(all_cases, 16, SEED)
    generated_ids = {case.id for case in generated}
    registry = load_review_registry()

    assert len(generated) == 214
    assert len({case.turns[0].question for case in generated}) == 192
    assert set(registry.cases) <= generated_ids
    assert sum(entry.review_status == "reviewed" for entry in registry.cases.values()) == 30
    assert sum(entry.review_status == "quarantined" for entry in registry.cases.values()) == 17
    assert sum(registry.entry_for(case.id).review_status == "unreviewed" for case in generated) == 167
