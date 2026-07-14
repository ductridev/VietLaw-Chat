"""Black-box HTTP client.

The evaluation system never imports backend business logic. Every observation
about a backend comes through this client, so both backend_lite and the
production backend are judged by exactly the same evidence.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


class BackendUnavailable(RuntimeError):
    """The target backend could not be reached at all (exit code 3)."""


@dataclass
class ApiResponse:
    status: int | None
    body: Any
    raw_text: str
    latency_ms: float
    headers: dict[str, str] = field(default_factory=dict)
    transport_error: str | None = None

    @property
    def json_body(self) -> dict[str, Any]:
        return self.body if isinstance(self.body, dict) else {}

    @property
    def is_json(self) -> bool:
        return isinstance(self.body, (dict, list))


class ApiClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        retries: int = 0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- transport -------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        text_body: str | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ApiResponse:
        url = f"{self.base_url}{path}"
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        content: bytes | None = None
        if text_body is not None:
            content = text_body.encode("utf-8")
        elif json_body is not None:
            content = json.dumps(json_body, ensure_ascii=False).encode("utf-8")

        attempt = 0
        last_error: str | None = None
        while attempt <= self.retries:
            started = time.perf_counter()
            try:
                response = self._client.request(
                    method,
                    url,
                    content=content,
                    params=params,
                    headers=request_headers if content is not None else (headers or None),
                )
                latency_ms = (time.perf_counter() - started) * 1000
                try:
                    body: Any = response.json()
                except (json.JSONDecodeError, ValueError):
                    body = None
                return ApiResponse(
                    status=response.status_code,
                    body=body,
                    raw_text=response.text,
                    latency_ms=latency_ms,
                    headers=dict(response.headers),
                )
            except httpx.HTTPError as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                last_error = f"{type(exc).__name__}: {exc}"
                attempt += 1
                if attempt > self.retries:
                    return ApiResponse(
                        status=None,
                        body=None,
                        raw_text="",
                        latency_ms=latency_ms,
                        transport_error=last_error,
                    )
                time.sleep(0.2 * attempt)
        return ApiResponse(status=None, body=None, raw_text="", latency_ms=0.0, transport_error=last_error)

    # -- API surface -----------------------------------------------------

    def health(self) -> ApiResponse:
        return self.request("GET", "/api/health")

    def analyze(self, payload: dict[str, Any]) -> ApiResponse:
        return self.request("POST", "/api/analyze", json_body=payload)

    def analyze_raw(self, text_body: str, headers: dict[str, str] | None = None) -> ApiResponse:
        return self.request("POST", "/api/analyze", text_body=text_body, headers=headers)

    def create_chat(self, payload: dict[str, Any]) -> ApiResponse:
        return self.request("POST", "/api/chats", json_body=payload)

    def list_chats(self, params: dict[str, Any]) -> ApiResponse:
        return self.request("GET", "/api/chats", params=params)

    def get_chat(self, chat_id: str, params: dict[str, Any]) -> ApiResponse:
        return self.request("GET", f"/api/chats/{chat_id}", params=params)

    def delete_chat(self, chat_id: str, params: dict[str, Any]) -> ApiResponse:
        return self.request("DELETE", f"/api/chats/{chat_id}", params=params)

    # -- readiness -------------------------------------------------------

    def wait_until_ready(self, attempts: int = 1, delay: float = 0.5) -> ApiResponse:
        last: ApiResponse | None = None
        for i in range(attempts):
            last = self.health()
            if last.status == 200:
                return last
            if i < attempts - 1:
                time.sleep(delay)
        if last is None or last.status is None:
            detail = last.transport_error if last else "no attempt made"
            raise BackendUnavailable(f"{self.base_url} is not reachable: {detail}")
        return last
