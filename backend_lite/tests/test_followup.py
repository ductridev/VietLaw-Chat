def test_followup_reuses_response_chat_id_and_context(client, analyze_payload):
    first = client.post(
        "/api/analyze",
        json=analyze_payload("Tôi thuê nhà, chủ nhà giữ tiền cọc 2 tháng không trả, tôi phải làm gì?"),
    ).json()
    second = client.post(
        "/api/analyze",
        json=analyze_payload("Vậy tôi cần chuẩn bị giấy tờ gì?", chat_id=first["chat_id"]),
    ).json()
    assert second["chat_id"] == first["chat_id"]
    assert second["domain"] == "civil_dispute"
    assert second["metadata"]["used_current_chat_history"] is True
    assert second["metadata"]["history_message_count"] == 2
    assert second["sources"]
    visible = " ".join([second["summary"], *second["checklist"], *second["next_steps"]]).lower()
    assert "tiền cọc" in visible


def test_same_generic_question_without_context_does_not_assume_deposit(client, analyze_payload):
    body = client.post(
        "/api/analyze",
        json=analyze_payload("Vậy tôi cần chuẩn bị giấy tờ gì?", session_id="fresh_generic"),
    ).json()
    assert body["domain"] == "unknown"
    assert body["sources"] == []


def test_chat_detail_preserves_all_turns_in_order(client, analyze_payload):
    first = client.post("/api/analyze", json=analyze_payload("Tôi hỏi về tiền cọc.")).json()
    client.post(
        "/api/analyze",
        json=analyze_payload("Vậy tôi cần chuẩn bị giấy tờ gì?", chat_id=first["chat_id"]),
    )
    messages = client.get(
        f"/api/chats/{first['chat_id']}", params={"session_id": "session_test"}
    ).json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]


def test_response_chat_id_is_backend_source_of_truth(client, analyze_payload):
    first = client.post("/api/analyze", json=analyze_payload("Tôi hỏi về tiền cọc.")).json()
    followup = client.post(
        "/api/analyze",
        json=analyze_payload("Vậy cần giấy tờ gì?", chat_id=first["chat_id"]),
    ).json()
    assert followup["chat_id"] == first["chat_id"]
