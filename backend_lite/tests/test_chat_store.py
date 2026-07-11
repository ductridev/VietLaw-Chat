from backend_lite.app.schemas.chat import ChatMessage
from backend_lite.app.stores.sqlite_chat_store import SQLiteChatStore


def test_sqlite_store_creates_required_indexes(settings):
    store = SQLiteChatStore(settings.chat_db_path)
    with store._connect() as connection:  # noqa: SLF001 - schema assertion
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(messages)").fetchall()}
        chat_indexes = {row[1] for row in connection.execute("PRAGMA index_list(chats)").fetchall()}
    assert "idx_messages_chat_created" in indexes
    assert "idx_chats_session_updated" in chat_indexes


def test_messages_order_created_at_then_message_id(settings):
    store = SQLiteChatStore(settings.chat_db_path)
    chat = store.create_chat("session_order")
    for message_id in ("msg_b", "msg_a"):
        store.add_message(
            ChatMessage(
                message_id=message_id,
                chat_id=chat.chat_id,
                role="user",
                content_type="text",
                content_text=message_id,
                content_json=None,
                created_at="2026-07-10T00:00:00+00:00",
            )
        )
    assert [message.message_id for message in store.list_messages(chat.chat_id)] == ["msg_a", "msg_b"]


def test_soft_deleted_chat_is_hidden(settings):
    store = SQLiteChatStore(settings.chat_db_path)
    chat = store.create_chat("session_delete")
    assert store.soft_delete(chat.chat_id) is True
    assert store.get_chat(chat.chat_id) is None
    assert store.list_chats("session_delete") == []


def test_session_scoped_store_methods_do_not_reveal_or_delete_other_session(settings):
    store = SQLiteChatStore(settings.chat_db_path)
    chat = store.create_chat("owner")
    assert store.get_chat_for_session(chat.chat_id, "other") is None
    assert store.soft_delete_chat_for_session(chat.chat_id, "other") is False
    assert store.get_chat_for_session(chat.chat_id, "owner") is not None
    assert store.soft_delete_chat_for_session(chat.chat_id, "owner") is True
