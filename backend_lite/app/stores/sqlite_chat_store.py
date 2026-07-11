from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..schemas.chat import ChatListItem, ChatMessage
from ..schemas.content import AnalyzeContent
from .chat_store import ChatRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteChatStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.ready = False
        self.error: str | None = None
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS chats (
                        chat_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        deleted_at TEXT NULL
                    );
                    CREATE TABLE IF NOT EXISTS messages (
                        message_id TEXT PRIMARY KEY,
                        chat_id TEXT NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                        content_type TEXT NOT NULL CHECK(content_type IN ('text', 'structured')),
                        content_text TEXT NULL,
                        content_json TEXT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(chat_id) REFERENCES chats(chat_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_chats_session_updated
                        ON chats(session_id, updated_at);
                    CREATE INDEX IF NOT EXISTS idx_messages_chat_created
                        ON messages(chat_id, created_at, message_id);
                    """
                )
                connection.execute("SELECT 1")
            self.ready = True
            self.error = None
        except Exception as exc:  # noqa: BLE001 - readiness is surfaced by health
            self.ready = False
            self.error = str(exc)

    def create_chat(self, session_id: str, title: str = "Chat mới") -> ChatRecord:
        chat_id = f"chat_{uuid4().hex}"
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO chats(chat_id, session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (chat_id, session_id, title or "Chat mới", now, now),
            )
        return ChatRecord(chat_id, session_id, title or "Chat mới", now, now)

    def get_chat(self, chat_id: str) -> ChatRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM chats WHERE chat_id = ? AND deleted_at IS NULL",
                (chat_id,),
            ).fetchone()
        return ChatRecord(**dict(row)) if row else None

    def get_chat_for_session(self, chat_id: str, session_id: str) -> ChatRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM chats
                WHERE chat_id = ? AND session_id = ? AND deleted_at IS NULL
                """,
                (chat_id, session_id),
            ).fetchone()
        return ChatRecord(**dict(row)) if row else None

    def add_message(self, message: ChatMessage) -> None:
        content_json = (
            json.dumps(message.content_json.model_dump(mode="json"), ensure_ascii=False)
            if message.content_json is not None
            else None
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages(message_id, chat_id, role, content_type, content_text, content_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.chat_id,
                    message.role,
                    message.content_type,
                    message.content_text,
                    content_json,
                    message.created_at,
                ),
            )
            connection.execute(
                "UPDATE chats SET updated_at = ? WHERE chat_id = ?",
                (message.created_at, message.chat_id),
            )

    def list_messages(self, chat_id: str, limit: int | None = None) -> list[ChatMessage]:
        with self._connect() as connection:
            if limit is None:
                rows = connection.execute(
                    "SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at ASC, message_id ASC",
                    (chat_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM (
                        SELECT * FROM messages WHERE chat_id = ?
                        ORDER BY created_at DESC, message_id DESC LIMIT ?
                    ) ORDER BY created_at ASC, message_id ASC
                    """,
                    (chat_id, limit),
                ).fetchall()
        messages: list[ChatMessage] = []
        for row in rows:
            raw = dict(row)
            parsed = json.loads(raw["content_json"]) if raw["content_json"] else None
            messages.append(
                ChatMessage(
                    message_id=raw["message_id"],
                    chat_id=raw["chat_id"],
                    role=raw["role"],
                    content_type=raw["content_type"],
                    content_text=raw["content_text"],
                    content_json=AnalyzeContent.model_validate(parsed) if parsed is not None else None,
                    created_at=raw["created_at"],
                )
            )
        return messages

    def list_chats(self, session_id: str) -> list[ChatListItem]:
        with self._connect() as connection:
            chats = connection.execute(
                "SELECT * FROM chats WHERE session_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC, chat_id DESC",
                (session_id,),
            ).fetchall()
        result: list[ChatListItem] = []
        for chat_row in chats:
            chat = dict(chat_row)
            messages = self.list_messages(chat["chat_id"])
            preview = ""
            domain = None
            risk_level = None
            if messages:
                latest = messages[-1]
                preview = latest.content_text or (latest.content_json.summary if latest.content_json else "")
                for message in reversed(messages):
                    if message.content_json is not None:
                        domain = message.content_json.domain
                        risk_level = message.content_json.risk_level
                        break
            result.append(
                ChatListItem(
                    chat_id=chat["chat_id"],
                    title=chat["title"],
                    created_at=chat["created_at"],
                    updated_at=chat["updated_at"],
                    last_message_preview=preview[:240],
                    domain=domain,
                    risk_level=risk_level,
                    message_count=len(messages),
                )
            )
        return result

    def soft_delete(self, chat_id: str) -> bool:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE chats SET deleted_at = ?, updated_at = ? WHERE chat_id = ? AND deleted_at IS NULL",
                (now, now, chat_id),
            )
        return cursor.rowcount > 0

    def soft_delete_chat_for_session(self, chat_id: str, session_id: str) -> bool:
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE chats SET deleted_at = ?, updated_at = ?
                WHERE chat_id = ? AND session_id = ? AND deleted_at IS NULL
                """,
                (now, now, chat_id, session_id),
            )
        return cursor.rowcount > 0
