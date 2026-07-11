from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..errors import RetrievalError
from ..schemas.content import Domain, SourceObject, SourceType


class SnippetRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    domain: Domain
    title: str
    source_name: str
    source_url: str | None = None
    source_type: SourceType
    status: str
    text: str
    plain_language_summary: str
    tags: list[str]
    risk_notes: list[str]
    last_checked: str

    def as_source(self) -> SourceObject:
        return SourceObject(
            id=self.id,
            title=self.title,
            source_name=self.source_name,
            url=self.source_url,
            snippet=self.plain_language_summary if self.source_type == "safety_policy" else self.text,
            source_type=self.source_type,
            last_checked=self.last_checked,
        )


class JsonSnippetStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.loaded = False
        self.error: str | None = None
        self._snippets: list[SnippetRecord] = []
        self.reload()

    def reload(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("legal snippets must be a JSON list")
            parsed = [SnippetRecord.model_validate(item) for item in raw]
            ids = [item.id for item in parsed]
            if len(ids) != len(set(ids)):
                raise ValueError("legal snippet ids must be unique")
            self._snippets = [item for item in parsed if item.status == "active"]
            self.loaded = True
            self.error = None
        except Exception as exc:  # noqa: BLE001 - load status is part of health
            self._snippets = []
            self.loaded = False
            self.error = str(exc)

    def ensure_ready(self) -> None:
        if not self.loaded:
            raise RetrievalError()

    def active_snippets(self) -> list[SnippetRecord]:
        self.ensure_ready()
        return list(self._snippets)
