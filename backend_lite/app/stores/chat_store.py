from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatRecord:
    chat_id: str
    session_id: str
    title: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None
