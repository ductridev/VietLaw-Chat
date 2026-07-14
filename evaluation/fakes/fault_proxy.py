"""A fault-injecting proxy that sits in front of a real backend.

Lets the harness exercise transport-level faults (timeouts, resets, truncated
bodies, 503 storms) against the *real* backend's traffic without modifying the
backend. Useful for verifying client resilience and error-path reporting.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx

FAULTS = ("none", "timeout", "reset", "truncate", "status_503", "corrupt_json", "drop_field")


class _ProxyHandler(BaseHTTPRequestHandler):
    upstream: str = ""
    fault: str = "none"
    delay_seconds: float = 10.0
    drop_field_name: str = "safety_notice"

    def log_message(self, *_args: Any) -> None:
        return

    def _proxy(self, method: str) -> None:
        fault = type(self).fault
        if fault == "reset":
            self.close_connection = True
            self.wfile.close()
            return
        if fault == "timeout":
            import time

            time.sleep(type(self).delay_seconds)

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        url = f"{type(self).upstream}{self.path}"
        try:
            with httpx.Client(timeout=30.0) as client:
                upstream = client.request(
                    method,
                    url,
                    content=body,
                    headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
                )
        except httpx.HTTPError as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(exc).encode())
            return

        payload = upstream.content
        status = upstream.status_code

        if fault == "status_503":
            status = 503
        elif fault == "corrupt_json":
            payload = payload[: max(1, len(payload) // 2)]
        elif fault == "truncate":
            payload = payload[:20]
        elif fault == "drop_field":
            import json

            try:
                data = json.loads(payload)
                data.pop(type(self).drop_field_name, None)
                payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            except ValueError:
                pass

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self._proxy("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._proxy("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy("DELETE")


class FaultProxy:
    def __init__(
        self,
        upstream: str,
        fault: str = "none",
        delay_seconds: float = 10.0,
        drop_field: str = "safety_notice",
    ) -> None:
        if fault not in FAULTS:
            raise ValueError(f"unknown fault {fault!r}; known: {FAULTS}")
        self.upstream = upstream.rstrip("/")
        self.fault = fault
        self.delay_seconds = delay_seconds
        self.drop_field = drop_field
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("proxy is not running")
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> FaultProxy:
        handler = type(
            "ScopedProxyHandler",
            (_ProxyHandler,),
            {
                "upstream": self.upstream,
                "fault": self.fault,
                "delay_seconds": self.delay_seconds,
                "drop_field_name": self.drop_field,
            },
        )
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
