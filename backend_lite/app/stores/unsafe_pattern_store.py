from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonUnsafePatternStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.loaded = False
        self.error: str | None = None
        self.data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("unsafe patterns must be a JSON object")
            for required in ("unsafe_intent_patterns", "high_risk_patterns", "unsupported_patterns"):
                if not isinstance(raw.get(required), list):
                    raise ValueError(f"missing or invalid {required}")
            self.data = raw
            self.loaded = True
            self.error = None
        except Exception as exc:  # noqa: BLE001
            self.data = {}
            self.loaded = False
            self.error = str(exc)

    def groups(self, name: str) -> list[dict[str, Any]]:
        value = self.data.get(name, [])
        return value if isinstance(value, list) else []

    def replacements(self) -> dict[str, str]:
        value = self.data.get("safe_replacement_phrases", {})
        return value if isinstance(value, dict) else {}
