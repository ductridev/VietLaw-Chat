def test_english_is_structured_unsupported_and_persisted(client, analyze_payload):
    response = client.post(
        "/api/analyze",
        json=analyze_payload("What documents do I need to start a food business in Vietnam?", user_type="foreign_visitor"),
    )
    body = response.json()
    assert response.status_code == 200
    assert (body["domain"], body["risk_level"], body["decision"]) == ("unknown", "low", "unsupported")
    assert body["sources"] == []
    messages = client.get(
        f"/api/chats/{body['chat_id']}", params={"session_id": "session_test"}
    ).json()["messages"]
    assert messages[-1]["content_json"]["decision"] == "unsupported"


def test_vietnamese_without_diacritics_is_supported(client, analyze_payload):
    body = client.post(
        "/api/analyze",
        json=analyze_payload("toi thue nha chu nha giu tien coc khong tra"),
    ).json()
    assert body["domain"] == "civil_dispute"
    assert body["decision"] != "unsupported"


def test_non_vi_language_flag_is_normal_unsupported(client, analyze_payload):
    body = client.post(
        "/api/analyze",
        json=analyze_payload("Tôi cần hỏi một vấn đề pháp lý.", language="en"),
    ).json()
    assert body["decision"] == "unsupported"
    assert body["sources"] == []
