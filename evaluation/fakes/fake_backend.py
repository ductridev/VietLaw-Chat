"""A scriptable broken backend, used to fault-test the harness itself.

This never touches the production backend. It lets the evaluation system prove
it reacts correctly to backends that time out, reset the connection, return
garbage, or return a well-formed-but-wrong response.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..dataset import SAFETY_NOTICE
from .mutants import MUTANTS, valid_chat_detail, valid_response

SCENARIOS = (
    "healthy",
    "slow_response",
    "invalid_json",
    "wrong_content_type",
    "http_429",
    "http_500",
    "http_503_retrieval_error",
    "http_422_instead_of_400",
    "missing_field",
    "null_content_json",
    "duplicate_message_ids",
    "cross_session_leak",
    "connection_reset",
    "empty_body",
    "degraded_health",
    *MUTANTS.keys(),
)


class _Handler(BaseHTTPRequestHandler):
    scenario: str = "healthy"
    delay_seconds: float = 0.0

    def log_message(self, *_args: Any) -> None:  # silence stderr noise
        return

    def finish(self) -> None:
        # The connection_reset scenario closes the socket mid-response on
        # purpose; swallow the resulting flush error so the self-test output
        # stays readable.
        try:
            super().finish()
        except (ValueError, BrokenPipeError, ConnectionResetError):
            pass

    # -- helpers ---------------------------------------------------------

    def _send(self, status: int, body: Any, content_type: str = "application/json") -> None:
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(
            status,
            {
                "contract_version": "v1",
                "request_id": "req_fake_error",
                "error": {"code": code, "message": message},
                "safety_notice": SAFETY_NOTICE,
            },
        )

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        scenario = type(self).scenario
        if self.path.startswith("/api/health"):
            if scenario == "degraded_health":
                self._send(
                    200,
                    {
                        "status": "degraded",
                        "service": "fake-backend",
                        "contract_version": "v1",
                        "rag_loaded": False,
                        "safety_loaded": True,
                        "chat_store_ready": True,
                    },
                )
                return
            self._send(
                200,
                {
                    "status": "ok",
                    "service": "fake-backend",
                    "contract_version": "v1",
                    "rag_loaded": True,
                    "safety_loaded": True,
                    "chat_store_ready": True,
                },
            )
            return

        if self.path.startswith("/api/chats/"):
            if scenario == "cross_session_leak":
                # Returns another session's chat with HTTP 200 instead of 404.
                self._send(200, valid_chat_detail())
                return
            detail = valid_chat_detail()
            if scenario == "null_content_json":
                detail["messages"][1]["content_json"] = None
            elif scenario == "duplicate_message_ids":
                detail["messages"][1]["message_id"] = detail["messages"][0]["message_id"]
            self._send(200, detail)
            return

        self._send(200, {"contract_version": "v1", "session_id": "s", "chats": []})

    def do_POST(self) -> None:  # noqa: N802
        scenario = type(self).scenario
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)

        if scenario == "connection_reset":
            self.close_connection = True
            self.wfile.close()
            return
        if scenario == "slow_response":
            time.sleep(type(self).delay_seconds or 5.0)
        if scenario == "invalid_json":
            self._send(200, b"{this is not valid json", content_type="application/json")
            return
        if scenario == "wrong_content_type":
            self._send(200, b"plain text answer", content_type="text/plain")
            return
        if scenario == "empty_body":
            self._send(200, b"")
            return
        if scenario == "http_429":
            self._error(429, "internal_error", "Too many requests")
            return
        if scenario == "http_500":
            self._error(500, "internal_error", "Backend gặp lỗi không mong đợi.")
            return
        if scenario == "http_503_retrieval_error":
            self._error(503, "retrieval_error", "RAG tạm thời không khả dụng.")
            return
        if scenario == "http_422_instead_of_400":
            self._send(422, {"detail": [{"loc": ["body", "question"], "msg": "field required"}]})
            return
        if scenario == "missing_field":
            response = valid_response()
            response.pop("assistant_message_id")
            self._send(200, response)
            return

        mutant = MUTANTS.get(scenario)
        if mutant is not None:
            self._send(200, mutant[0](valid_response()))
            return

        self._send(200, valid_response())

    def do_DELETE(self) -> None:  # noqa: N802
        self._send(200, {"contract_version": "v1", "chat_id": "chat_test_001", "deleted": True})


class FakeBackend:
    """Context manager that serves one scenario on an ephemeral port."""

    def __init__(self, scenario: str = "healthy", delay_seconds: float = 0.0) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        self.scenario = scenario
        self.delay_seconds = delay_seconds
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("server is not running")
        host, port = self._server.server_address[:2]
        return f"http://127.0.0.1:{port}"

    def __enter__(self) -> FakeBackend:
        handler = type("ScopedHandler", (_Handler,), {"scenario": self.scenario, "delay_seconds": self.delay_seconds})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
