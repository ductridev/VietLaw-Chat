"""Optional local backend process management.

Used only when the caller passes --start-command. The evaluation system never
requires the ability to start a backend: if a backend is already listening, it
is evaluated as-is.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .api_client import ApiClient, BackendUnavailable


@dataclass
class ManagedBackend:
    process: subprocess.Popen[bytes]
    base_url: str
    log_path: Path

    @property
    def pid(self) -> int:
        return self.process.pid


class ProcessManager:
    """Start a backend, wait for /api/health, and always stop it cleanly."""

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._managed: ManagedBackend | None = None

    def start(
        self,
        command: str,
        base_url: str,
        env: dict[str, str] | None = None,
        wait_seconds: float = 30.0,
    ) -> ManagedBackend:
        log_path = self.log_dir / "backend.log"
        merged_env = {**os.environ, **(env or {})}
        handle = log_path.open("wb")
        process = subprocess.Popen(  # noqa: S603 - command comes from the operator
            shlex.split(command),
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=merged_env,
            start_new_session=True,
        )
        managed = ManagedBackend(process=process, base_url=base_url, log_path=log_path)
        self._managed = managed

        deadline = time.time() + wait_seconds
        with ApiClient(base_url, timeout=5.0) as client:
            while time.time() < deadline:
                if process.poll() is not None:
                    tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                    raise BackendUnavailable(
                        f"backend exited with code {process.returncode} before becoming healthy:\n{tail}"
                    )
                probe = client.health()
                if probe.status == 200:
                    return managed
                time.sleep(0.4)
        self.stop()
        raise BackendUnavailable(f"backend at {base_url} did not become healthy within {wait_seconds}s")

    def stop(self) -> None:
        managed = self._managed
        if managed is None or managed.process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(managed.pid), signal.SIGINT)
            managed.process.wait(timeout=10)
        except (ProcessLookupError, PermissionError):
            pass
        except subprocess.TimeoutExpired:
            managed.process.kill()
            managed.process.wait(timeout=5)
        finally:
            self._managed = None

    def __enter__(self) -> ProcessManager:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()
