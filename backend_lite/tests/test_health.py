from pathlib import Path

from fastapi.testclient import TestClient

from backend_lite.app.config import Settings
from backend_lite.app.main import create_app


def test_health_all_ready(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "vietlaw-chat-backend",
        "contract_version": "v1",
        "rag_loaded": True,
        "safety_loaded": True,
        "chat_store_ready": True,
    }


def test_health_degraded_when_snippets_missing(settings: Settings, tmp_path: Path):
    degraded = settings.model_copy(update={"legal_snippets_path": tmp_path / "missing.json"})
    with TestClient(create_app(degraded)) as test_client:
        body = test_client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["rag_loaded"] is False
    assert body["safety_loaded"] is True
