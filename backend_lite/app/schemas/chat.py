from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .content import AnalyzeContent, Domain, RiskLevel


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    chat_id: str
    role: Literal["user", "assistant"]
    content_type: Literal["text", "structured"]
    content_text: str | None
    content_json: AnalyzeContent | None
    created_at: str


class ChatListItem(BaseModel):
    chat_id: str
    title: str
    created_at: str
    updated_at: str
    last_message_preview: str = ""
    domain: Domain | None = None
    risk_level: RiskLevel | None = None
    message_count: int = 0


class ChatCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=160)


class ChatCreateResponse(BaseModel):
    contract_version: Literal["v1"] = "v1"
    chat_id: str
    session_id: str
    title: str
    created_at: str
    updated_at: str


class ChatListResponse(BaseModel):
    contract_version: Literal["v1"] = "v1"
    session_id: str
    chats: list[ChatListItem]


class ChatDetailResponse(BaseModel):
    contract_version: Literal["v1"] = "v1"
    chat_id: str
    session_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[ChatMessage]


class DeleteChatResponse(BaseModel):
    contract_version: Literal["v1"] = "v1"
    chat_id: str
    deleted: bool
