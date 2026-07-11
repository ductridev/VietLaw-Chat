from __future__ import annotations

from ..runtime.agent_state import AgentState
from ..stores.sqlite_chat_store import SQLiteChatStore
from .input_normalizer import InputNormalizer


class SameChatContextBuilder:
    def __init__(self, store: SQLiteChatStore, normalizer: InputNormalizer, message_limit: int = 8) -> None:
        self.store = store
        self.normalizer = normalizer
        self.message_limit = message_limit

    def build(self, state: AgentState) -> None:
        messages = self.store.list_messages(state.chat.chat_id, limit=self.message_limit + 1)
        prior = [m for m in messages if m.message_id != state.persistence.user_message_id]
        state.chat.history_messages = prior[-self.message_limit:]
        state.chat.history_message_count = len(state.chat.history_messages)
        state.chat.used_current_chat_history = bool(state.chat.history_messages)

        terms: list[str] = []
        for message in state.chat.history_messages:
            if message.content_text:
                _, accentless = self.normalizer.normalize(message.content_text)
                terms.append(accentless)
            elif message.content_json:
                text = " ".join(
                    [message.content_json.summary, *message.content_json.checklist, *message.content_json.next_steps]
                )
                _, accentless = self.normalizer.normalize(text)
                terms.append(accentless)
        state.chat.context_topic_terms = terms
