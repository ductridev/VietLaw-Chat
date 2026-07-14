"""Execute one case: build requests, drive the API, apply the oracles.

Session discipline (api_contract.md §18.1): every case gets its own fresh
session id and never reuses a chat across runs, so cases cannot contaminate
each other and a rerun is independent of history left by the last one.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..clients.api_client import ApiClient, ApiResponse
from ..dataset import Corpus, load_corpus
from ..oracles import TURN_ORACLES, human_review_oracle
from ..oracles.base import TurnContext
from ..schemas.case import EvalCase, Turn
from ..schemas.report import HumanReviewItem
from ..schemas.result import CaseResult, Check, CheckStatus, TurnResult


@dataclass
class CaseExecution:
    result: CaseResult
    human_review: list[HumanReviewItem] = field(default_factory=list)
    raw_responses: list[ApiResponse] = field(default_factory=list)


class CaseRunner:
    def __init__(self, client: ApiClient, corpus: Corpus | None = None, run_id: str = "local") -> None:
        self.client = client
        self.corpus = corpus or load_corpus()
        self.run_id = run_id

    # -- session/chat state ---------------------------------------------

    def _session_ids(self, case: EvalCase) -> dict[str, str]:
        nonce = uuid.uuid4().hex[:10]
        return {
            "primary": f"eval-{self.run_id[:8]}-{case.id[:40]}-{nonce}",
            "attacker": f"eval-attacker-{nonce}",
        }

    def run(self, case: EvalCase) -> CaseExecution:
        started = time.perf_counter()
        sessions = self._session_ids(case)
        result = CaseResult(
            case_id=case.id,
            title=case.title,
            suite=case.suite,
            severity=case.severity,
            tags=list(case.tags),
            requirement_ids=list(case.requirement_ids),
            generated=case.generated,
        )
        execution = CaseExecution(result=result)

        last_chat_id: str | None = None
        first_chat_id: str | None = None
        fresh_index = 0

        for index, turn in enumerate(case.turns, start=1):
            if turn.session == "fresh" and index > 1:
                fresh_index += 1
                sessions["primary"] = f"{sessions['primary']}-f{fresh_index}"

            session_id = sessions["attacker"] if turn.session == "attacker" else sessions["primary"]
            owner_session_id = sessions["primary"]
            chat_id = self._resolve_chat_id(turn, last_chat_id)

            response, payload = self._execute(turn, session_id, chat_id)
            if turn.session == "attacker":
                # The oracle needs to know what the attacker was probing for.
                payload["_owner_session_id"] = owner_session_id
                payload["_owner_chat_id"] = chat_id or last_chat_id
            execution.raw_responses.append(response)

            body = response.json_body
            if turn.op == "analyze" and response.status == 200 and body.get("chat_id"):
                if first_chat_id is None:
                    first_chat_id = str(body["chat_id"])
                last_chat_id = str(body["chat_id"])
            elif turn.op == "chat_create" and response.status == 200 and body.get("chat_id"):
                last_chat_id = str(body["chat_id"])

            reload_detail = self._reload_if_needed(turn, session_id, last_chat_id)

            ctx = TurnContext(
                case=case,
                turn=turn,
                index=index,
                response=response,
                corpus=self.corpus,
                expectation=turn.expected,
                reload_detail=reload_detail,
                expected_chat_id=chat_id if turn.reuse_chat_id else None,
                first_chat_id=first_chat_id if index > 1 else None,
                request_payload=payload,
            )
            checks: list[Check] = []
            for oracle in TURN_ORACLES:
                checks.extend(oracle.evaluate(ctx))

            reasons = human_review_oracle.review_reasons(ctx)
            if reasons:
                execution.human_review.append(human_review_oracle.build_item(ctx, reasons))
                result.human_review_reasons.extend(reasons)

            result.turns.append(
                TurnResult(
                    index=index,
                    op=turn.op,
                    request={k: v for k, v in payload.items() if not k.startswith("_")},
                    http_status=response.status,
                    response=response.body,
                    latency_ms=response.latency_ms,
                    transport_error=response.transport_error,
                    checks=checks,
                )
            )

        result.duration_ms = (time.perf_counter() - started) * 1000
        result.finalize()
        return execution

    @staticmethod
    def _resolve_chat_id(turn: Turn, last_chat_id: str | None) -> str | None:
        if turn.reuse_chat_id:
            return last_chat_id
        if turn.chat_id == "$prev":
            return last_chat_id
        return turn.chat_id

    def _reload_if_needed(self, turn: Turn, session_id: str, chat_id: str | None) -> ApiResponse | None:
        needs = turn.expected.requires_persistence or turn.expected.requires_reload_equivalence
        if not needs or turn.op != "analyze" or not chat_id:
            return None
        return self.client.get_chat(chat_id, {"session_id": session_id})

    # -- request construction --------------------------------------------

    def _execute(self, turn: Turn, session_id: str, chat_id: str | None) -> tuple[ApiResponse, dict[str, Any]]:
        if turn.raw_body is not None:
            text = turn.raw_body if isinstance(turn.raw_body, str) else None
            if text is not None:
                headers = {"Content-Type": "text/plain"} if turn.raw_body_is_text else None
                return self.client.analyze_raw(text, headers=headers), {"_raw_body": text}
            return self.client.analyze(turn.raw_body), {"_raw_body": turn.raw_body}

        if turn.op == "health":
            return self.client.health(), {}

        if turn.op == "analyze":
            payload: dict[str, Any] = {
                "question": turn.question,
                "user_type": turn.user_type,
                "language": turn.language,
                "session_id": session_id,
            }
            if chat_id is not None:
                payload["chat_id"] = chat_id
            if turn.omit_session_id:
                payload.pop("session_id", None)
            if turn.omit_question:
                payload.pop("question", None)
            payload.update(turn.query_overrides)
            payload = {k: v for k, v in payload.items() if v is not None or k in turn.query_overrides}
            return self.client.analyze(payload), payload

        params: dict[str, Any] = {} if turn.omit_session_id else {"session_id": session_id}
        params.update(turn.query_overrides)

        if turn.op == "chat_create":
            body: dict[str, Any] = {} if turn.omit_session_id else {"session_id": session_id}
            if turn.title is not None:
                body["title"] = turn.title
            body.update(turn.query_overrides)
            return self.client.create_chat(body), body
        if turn.op == "chat_list":
            return self.client.list_chats(params), params
        if turn.op == "chat_detail":
            return self.client.get_chat(chat_id or "chat_missing", params), {**params, "chat_id": chat_id}
        if turn.op == "chat_delete":
            return self.client.delete_chat(chat_id or "chat_missing", params), {**params, "chat_id": chat_id}

        raise ValueError(f"unsupported op {turn.op!r}")


def error_result(case: EvalCase, message: str) -> CaseResult:
    """Represent a runner-level failure as a failed case, never as a silent pass."""
    result = CaseResult(
        case_id=case.id,
        title=case.title,
        suite=case.suite,
        severity=case.severity,
        tags=list(case.tags),
        requirement_ids=list(case.requirement_ids),
        generated=case.generated,
        turns=[
            TurnResult(
                index=1,
                op=case.turns[0].op,
                checks=[
                    Check(
                        name="runner_error",
                        oracle="runner",
                        status=CheckStatus.ERROR,
                        severity="blocker",
                        message=message,
                    )
                ],
            )
        ],
    )
    return result.finalize()
