from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend_lite.app.config import Settings
from backend_lite.app.main import create_app
from backend_lite.app.runtime.agent_state import AgentState, RequestState
from backend_lite.app.schemas.content import GeneratedContent


def test_civil_deposit_retrieves_approved_sources(client, analyze_payload):
    body = client.post(
        "/api/analyze",
        json=analyze_payload("Tôi thuê nhà, chủ nhà giữ tiền cọc không trả."),
    ).json()
    ids = {source["id"] for source in body["sources"]}
    assert "civil_deposit_001" in ids or "civil_rental_001" in ids
    assert all(source["id"] for source in body["sources"])


def test_generic_new_chat_does_not_fake_sources(client, analyze_payload):
    body = client.post(
        "/api/analyze",
        json=analyze_payload("Tôi có một vấn đề pháp lý rất lạ nhưng chưa mô tả rõ, tôi phải làm gì?"),
    ).json()
    assert body["sources"] == []
    assert body["metadata"]["has_sources"] is False


def test_missing_snippet_store_returns_retrieval_error(settings: Settings, tmp_path: Path):
    broken = settings.model_copy(update={"legal_snippets_path": tmp_path / "missing.json"})
    with TestClient(create_app(broken)) as test_client:
        response = test_client.post(
            "/api/analyze",
            json={"session_id": "broken", "question": "Tôi hỏi về tiền cọc.", "language": "vi"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "retrieval_error"


def test_citation_guard_removes_unknown_source_id(app):
    state = AgentState(RequestState("req", "v1", "s", None, "q", "citizen", "vi"))
    state.retrieval.retrieved_source_ids = ["allowed"]
    state.generation.generated_content = GeneratedContent(
        summary="summary",
        clarifying_questions=[],
        checklist=[],
        next_steps=[],
        used_source_ids=["allowed", "invented"],
    )
    guarded = app.state.container.runtime.citation_guard.apply(state)
    assert guarded.content.used_source_ids == ["allowed"]
    assert guarded.removed_source_ids == ["invented"]
    assert guarded.confidence_adjustment == -0.2
    assert "citation_guard_removed_unknown_source_ids" in state.trace.warnings


def test_citation_guard_valid_subset_is_unchanged(app):
    state = AgentState(RequestState("req", "v1", "s", None, "q", "citizen", "vi"))
    state.retrieval.retrieved_source_ids = ["allowed"]
    original = GeneratedContent(
        summary="Nội dung thận trọng.",
        clarifying_questions=[],
        checklist=[],
        next_steps=[],
        used_source_ids=["allowed"],
    )
    state.generation.generated_content = original
    result = app.state.container.runtime.citation_guard.apply(state)
    assert result.content == original
    assert result.removed_source_ids == []
    assert result.guard_triggered is False
    assert result.confidence_adjustment is None


def test_invalid_citation_cautions_strong_claim_and_reduces_response_confidence(
    app, analyze_payload, monkeypatch
):
    class InventingGenerator:
        model_name = "fault_injection"
        used_llm = True

        async def generate(self, _state):
            return GeneratedContent(
                summary="Theo luật, bạn chắc chắn có quyền yêu cầu bên kia trả tiền ngay.",
                clarifying_questions=[],
                checklist=[],
                next_steps=["Bắt buộc bên kia thực hiện ngay."],
                used_source_ids=["invented_source"],
            )

    monkeypatch.setattr(app.state.container.runtime, "content_generator", InventingGenerator())
    with TestClient(app) as test_client:
        body = test_client.post(
            "/api/analyze", json=analyze_payload("Tôi thuê nhà bị giữ tiền cọc.")
        ).json()
    assert body["sources"] == []
    assert "chưa có nguồn đủ phù hợp" in body["summary"]
    assert body["confidence"]["answer"] < 0.48
    assert body["metadata"]["citation_removed_source_ids"] == ["invented_source"]
    assert body["metadata"]["citation_content_cautioned"] is True
    assert "citation_guard_cautioned_unsupported_claim" in body["metadata"]["guard_warnings"]


@pytest.mark.parametrize(
    "question,expected_domain,required_ids,forbidden_ids",
    [
        (
            "Chủ trọ cứ khất chưa hoàn lại khoản cọc cho tôi",
            "civil_dispute",
            {"civil_deposit_001", "civil_rental_001"},
            {"traffic_safety_001"},
        ),
        (
            "Tôi đọc biên bản nhưng chẳng hiểu mình bị lỗi gì",
            "traffic",
            {"traffic_fine_001"},
            {"civil_loan_001"},
        ),
        (
            "Tôi bán đồ ăn qua Facebook tại nhà thì phải đăng ký gì",
            "household_business",
            {"business_food_001", "business_food_002", "business_registration_001"},
            {"traffic_safety_001", "civil_loan_001"},
        ),
        (
            "Tôi cho bạn vay tiền nhưng họ cứ tránh mặt",
            "civil_dispute",
            {"civil_loan_001"},
            {"traffic_safety_001", "civil_rental_001"},
        ),
    ],
)
def test_unseen_paraphrases_retrieve_only_relevant_sources(
    client, analyze_payload, question, expected_domain, required_ids, forbidden_ids
):
    body = client.post("/api/analyze", json=analyze_payload(question)).json()
    ids = {source["id"] for source in body["sources"]}
    assert body["domain"] == expected_domain
    assert ids & required_ids
    assert not ids & forbidden_ids


def test_unseen_no_match_paraphrase_returns_no_source(client, analyze_payload):
    body = client.post(
        "/api/analyze",
        json=analyze_payload("Tôi muốn hỏi một chủ đề pháp lý hoàn toàn không có trong dữ liệu"),
    ).json()
    assert body["domain"] == "unknown"
    assert body["decision"] == "ask_clarifying_questions"
    assert body["sources"] == []


def test_administrative_business_query_can_use_compatible_business_procedure_sources(
    client, analyze_payload
):
    body = client.post(
        "/api/analyze",
        json=analyze_payload(
            "Tôi muốn hỏi thủ tục đăng ký kinh doanh tại địa phương.",
            user_type="household_business",
        ),
    ).json()
    ids = {source["id"] for source in body["sources"]}
    assert body["domain"] == "administrative"
    assert ids
    assert ids <= {
        "business_registration_001",
        "business_registration_002",
        "business_registration_003",
        "business_checklist_001",
    }
