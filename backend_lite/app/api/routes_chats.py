from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..constants import CONTRACT_VERSION
from ..dependencies import AppContainer, get_container
from ..errors import ChatNotFoundError
from ..schemas.chat import (
    ChatCreateRequest,
    ChatCreateResponse,
    ChatDetailResponse,
    ChatListResponse,
    DeleteChatResponse,
)

router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.post("", response_model=ChatCreateResponse)
def create_chat(
    payload: ChatCreateRequest,
    container: AppContainer = Depends(get_container),
) -> ChatCreateResponse:
    chat = container.chat_store.create_chat(payload.session_id, payload.title or "Chat mới")
    return ChatCreateResponse(contract_version=CONTRACT_VERSION, **chat.__dict__)


@router.get("", response_model=ChatListResponse)
def list_chats(
    session_id: str = Query(min_length=1, max_length=128),
    container: AppContainer = Depends(get_container),
) -> ChatListResponse:
    return ChatListResponse(
        contract_version=CONTRACT_VERSION,
        session_id=session_id,
        chats=container.chat_store.list_chats(session_id),
    )


@router.get("/{chat_id}", response_model=ChatDetailResponse)
def get_chat(
    chat_id: str,
    session_id: str = Query(min_length=1, max_length=128),
    container: AppContainer = Depends(get_container),
) -> ChatDetailResponse:
    chat = container.chat_store.get_chat_for_session(chat_id, session_id)
    if chat is None:
        raise ChatNotFoundError()
    return ChatDetailResponse(
        contract_version=CONTRACT_VERSION,
        chat_id=chat.chat_id,
        session_id=chat.session_id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=container.chat_store.list_messages(chat_id),
    )


@router.delete("/{chat_id}", response_model=DeleteChatResponse)
def delete_chat(
    chat_id: str,
    session_id: str = Query(min_length=1, max_length=128),
    container: AppContainer = Depends(get_container),
) -> DeleteChatResponse:
    if not container.chat_store.soft_delete_chat_for_session(chat_id, session_id):
        raise ChatNotFoundError()
    return DeleteChatResponse(contract_version=CONTRACT_VERSION, chat_id=chat_id, deleted=True)
