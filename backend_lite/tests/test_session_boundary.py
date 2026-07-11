def test_followup_session_mismatch_is_404(client, analyze_payload):
    first = client.post(
        "/api/analyze",
        json=analyze_payload("Tôi hỏi về tiền cọc.", "owner_session"),
    ).json()
    response = client.post(
        "/api/analyze",
        json=analyze_payload("Vậy cần giấy tờ gì?", "other_session", chat_id=first["chat_id"]),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "chat_not_found"


def test_missing_chat_is_404_error_envelope(client, analyze_payload, safety_notice):
    response = client.post(
        "/api/analyze",
        json=analyze_payload("Tôi hỏi một vấn đề pháp lý.", chat_id="chat_missing"),
    )
    body = response.json()
    assert response.status_code == 404
    assert body["contract_version"] == "v1"
    assert body["error"]["code"] == "chat_not_found"
    assert body["safety_notice"] == safety_notice


def test_chat_detail_requires_correct_session_without_disclosure(client, analyze_payload):
    chat = client.post(
        "/api/analyze", json=analyze_payload("Tôi hỏi về tiền cọc.", "owner")
    ).json()
    missing = client.get(f"/api/chats/{chat['chat_id']}")
    wrong = client.get(f"/api/chats/{chat['chat_id']}", params={"session_id": "other"})
    correct = client.get(f"/api/chats/{chat['chat_id']}", params={"session_id": "owner"})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "invalid_request"
    assert wrong.status_code == 404
    assert wrong.json()["error"]["code"] == "chat_not_found"
    assert "owner" not in wrong.text
    assert correct.status_code == 200
    assert correct.json()["session_id"] == "owner"


def test_delete_requires_correct_session_without_disclosure(client, analyze_payload):
    chat = client.post(
        "/api/analyze", json=analyze_payload("Tôi hỏi về tiền cọc.", "owner")
    ).json()
    missing = client.delete(f"/api/chats/{chat['chat_id']}")
    wrong = client.delete(f"/api/chats/{chat['chat_id']}", params={"session_id": "other"})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "invalid_request"
    assert wrong.status_code == 404
    assert wrong.json()["error"]["code"] == "chat_not_found"
    assert "owner" not in wrong.text
    assert client.get(
        f"/api/chats/{chat['chat_id']}", params={"session_id": "owner"}
    ).status_code == 200
    deleted = client.delete(f"/api/chats/{chat['chat_id']}", params={"session_id": "owner"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
