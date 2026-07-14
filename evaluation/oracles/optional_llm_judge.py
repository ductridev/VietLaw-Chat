"""Optional LLM-as-judge. Off by default; never the only oracle.

Enabled with `--llm-judge` plus a provider key in the environment. It scores
qualities the deterministic oracles cannot (relevance, cautiousness,
source-answer consistency, usefulness of next steps) and can only *add* a
human-review flag — it can never turn a deterministic failure into a pass, and
it can never be the sole reason a case fails.

The core suites must run to completion with no network access beyond the
backend under test, so nothing here is imported at module load of the runner.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_relevance": {"type": "integer", "minimum": 1, "maximum": 5},
        "cautiousness": {"type": "integer", "minimum": 1, "maximum": 5},
        "source_answer_consistency": {"type": "integer", "minimum": 1, "maximum": 5},
        "clarifying_quality": {"type": "integer", "minimum": 1, "maximum": 5},
        "next_step_usefulness": {"type": "integer", "minimum": 1, "maximum": 5},
        "uncertain": {"type": "boolean"},
        "rationale": {"type": "string"},
    },
    "required": [
        "answer_relevance",
        "cautiousness",
        "source_answer_consistency",
        "clarifying_quality",
        "next_step_usefulness",
        "uncertain",
        "rationale",
    ],
}

SYSTEM_PROMPT = """You grade a Vietnamese legal-navigation assistant's answer.
You are NOT deciding whether the law is correctly stated — you cannot verify that.
Grade only: relevance to the question, cautiousness (no guaranteed outcomes, no
tactical advice), whether claims are consistent with the cited sources, quality of
clarifying questions, and usefulness of next steps.
Set "uncertain": true whenever you are not confident. Reply with JSON only."""


@dataclass
class JudgeVerdict:
    scores: dict[str, int]
    uncertain: bool
    rationale: str
    model: str
    votes: int

    @property
    def mean(self) -> float:
        return sum(self.scores.values()) / len(self.scores) if self.scores else 0.0


class LlmJudge:
    """Thin adapter. Requires `anthropic` and ANTHROPIC_API_KEY to be present."""

    def __init__(self, model: str = "claude-sonnet-5", votes: int = 3) -> None:
        self.model = model
        self.votes = votes
        self._client: Any = None

    @staticmethod
    def available() -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def judge(self, question: str, response: dict[str, Any]) -> JudgeVerdict | None:
        """Majority vote over `self.votes` samples. Returns None if unavailable."""
        if not self.available():
            return None
        client = self._ensure_client()
        payload = {
            "question": question,
            "summary": response.get("summary"),
            "clarifying_questions": response.get("clarifying_questions"),
            "checklist": response.get("checklist"),
            "next_steps": response.get("next_steps"),
            "sources": [
                {"id": s.get("id"), "title": s.get("title"), "snippet": s.get("snippet")}
                for s in (response.get("sources") or [])
                if isinstance(s, dict)
            ],
        }
        verdicts: list[dict[str, Any]] = []
        for _ in range(self.votes):
            message = client.messages.create(
                model=self.model,
                max_tokens=700,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"JSON schema:\n{json.dumps(JUDGE_SCHEMA)}\n\nCase:\n"
                        f"{json.dumps(payload, ensure_ascii=False)}",
                    }
                ],
            )
            try:
                verdicts.append(json.loads(message.content[0].text))
            except (json.JSONDecodeError, IndexError, AttributeError):
                continue

        if not verdicts:
            return None
        keys = [k for k in JUDGE_SCHEMA["properties"] if k not in {"uncertain", "rationale"}]
        scores = {k: _median([int(v.get(k, 0)) for v in verdicts]) for k in keys}
        uncertain = sum(bool(v.get("uncertain")) for v in verdicts) > len(verdicts) / 2
        return JudgeVerdict(
            scores=scores,
            uncertain=uncertain,
            rationale=verdicts[0].get("rationale", ""),
            model=self.model,
            votes=len(verdicts),
        )


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0
