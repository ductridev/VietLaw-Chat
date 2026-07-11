from __future__ import annotations

from typing import Protocol

from ..runtime.agent_state import AgentState
from ..schemas.content import GeneratedContent


class ContentGenerator(Protocol):
    model_name: str
    used_llm: bool

    async def generate(self, state: AgentState) -> GeneratedContent: ...
