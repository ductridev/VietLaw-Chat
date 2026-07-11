def analyze_content_from_response(body: dict) -> dict:
    keys = {
        "domain", "risk_level", "decision", "summary", "clarifying_questions", "checklist",
        "next_steps", "sources", "safety_notice", "confidence", "metadata",
    }
    return {key: body[key] for key in keys}


def test_optimistic_analyze_content_equals_reloaded_content(client, analyze_payload):
    body = client.post(
        "/api/analyze",
        json=analyze_payload("Tôi muốn bán đồ ăn online ở quê thì cần giấy tờ gì?", user_type="household_business"),
    ).json()
    reloaded = client.get(
        f"/api/chats/{body['chat_id']}", params={"session_id": "session_test"}
    ).json()["messages"][-1]["content_json"]
    assert reloaded == analyze_content_from_response(body)


def test_cors_preflight_for_frontend_origin(client):
    response = client.options(
        "/api/analyze",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_cors_preflight_rejects_disallowed_origin(client):
    response = client.options(
        "/api/analyze",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_unsupported_is_success_not_error_banner_condition(client, analyze_payload):
    response = client.post("/api/analyze", json=analyze_payload("Viết cho tôi bài thơ tình."))
    assert response.status_code == 200
    assert response.json()["decision"] == "unsupported"


def test_invalid_generated_response_is_not_stored_as_assistant(app, analyze_payload, monkeypatch):
    class InvalidResponse:
        def model_dump(self, *args, **kwargs):
            return {"contract_version": "v1"}

    monkeypatch.setattr(app.state.container.runtime.response_builder, "build", lambda _state: InvalidResponse())
    with TestClient(app, raise_server_exceptions=False) as safe_client:
        response = safe_client.post(
            "/api/analyze",
            json=analyze_payload("Tôi hỏi về tiền cọc.", "invalid_generation"),
        )
    assert response.status_code == 500
    chats = app.state.container.chat_store.list_chats("invalid_generation")
    assert len(chats) == 1
    messages = app.state.container.chat_store.list_messages(chats[0].chat_id)
    assert [message.role for message in messages] == ["user"]
from fastapi.testclient import TestClient


