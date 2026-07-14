# ADR-001: Bounded, State-First Legal-Navigation Pipeline

- **Status:** PROPOSED — ready for architecture review; no implementation is authorized by this ADR
- **Scope:** VietLaw-Chat MVP request execution, with Gate A as the first implementation slice
- **Depends on:** `docs/api_contract.md`, `docs/ai_core_spec.md`, `docs/rag_spec.md`, `docs/safety_policy.md`, ADR-002, ADR-003, ADR-004, ADR-005, ADR-007
- **Supersedes:** any interpretation of the MVP as an autonomous agent; it does not by itself supersede the frozen public API contract

## Decision markers

- **DECIDED:** locked by the approved architecture direction or frozen MVP semantics.
- **PROPOSED:** implementation direction that remains reviewable without weakening a locked boundary.
- **OWNER_DECISION_REQUIRED:** a product or public-contract choice that must be approved before dependent code is written.
- **DEFERRED:** explicitly outside Gate A.

## Context and problem

VietLaw-Chat performs legal navigation: it validates a request, recognizes safety and legal-risk signals, retrieves from a small approved corpus, selects evidence, chooses a response mode, renders a structured answer, guards the result, persists the exchange, and returns the frozen API shape. This is a bounded workflow with a known terminal response. It does not need an agent that invents goals, selects arbitrary tools, plans recursively, or keeps acting after the response.

The current fallback backend already contains a useful migration anchor:

- `backend_lite/app/runtime/agent_runtime.py` defines `AgentRuntime.analyze()` as the actual 18-phase orchestrator.
- `backend_lite/app/runtime/agent_state.py` aggregates request, chat, classification, retrieval, generation, guard, persistence, and trace dataclasses in `AgentState`.
- `backend_lite/app/runtime/phases.py` lists the current phase names, although the runtime does not consume that tuple as its transition authority.
- `backend_lite/app/dependencies.py::build_container()` constructs the concrete stores and services; `backend_lite/app/main.py::create_app()` invokes that container builder. The analyze route is a thin delegate.
- `LiteContentGenerator` is deterministic and advertises `used_llm = False`; `KeywordRagRetriever` is lexical/topic-gated; `LiteCitationGuard`, `LiteSafetyGuard`, and `LiteResponseBuilder` provide current guard/finalization anchors.

Those names must not be mistaken for the target architecture. There is currently no `application/`, `contracts/`, `pipeline/`, `adapters/`, or `observability/` package under `backend_lite/app`; there is no `AnalyzeService`, `AnalysisState`, `AnswerPlan`, evidence bundle, idempotency state machine, or `TraceSink`. Gate A is a controlled migration from the current anchors, not a second implementation beside them.

The current order also differs materially from the target. It creates or resolves a chat, stores a user message, and loads up to eight prior messages before current-turn normalization and safety detection. It has no request fingerprint or replay state. A failure after the user write leaves a user-only turn, and concurrent same-chat requests may interleave. The new architecture must make those boundaries explicit without changing the frozen API accidentally.

## Decision

**DECIDED:** VietLaw-Chat MVP is a bounded, state-first legal-navigation pipeline. It is not an autonomous agent and is not a reduced TOMTIT Core.

For one accepted execution attempt, the only allowed happy-path order is:

```text
validation
  -> ownership
  -> idempotency
  -> persist accepted request and user message
  -> activate request-scoped AnalysisState
  -> current-turn safety
  -> minimal bounded context
  -> routing
  -> lexical retrieval
  -> evidence selection
  -> authoritative backend decision
  -> deterministic AnswerPlan
  -> deterministic generation/rendering
  -> schema, evidence, and output-safety guards
  -> backend finalization
  -> persist assistant and final response
  -> response
```

“State-first” means that, after admission and the first durable transaction, every analysis-stage input and output is carried through one request-scoped `AnalysisState`. It does not mean untrusted input becomes authoritative before validation, nor that the whole state is persisted. A minimal immutable `AnalyzeCommand` may exist during validation, ownership, and idempotency admission. Object allocation before or after that boundary is an implementation detail; `AnalysisState` becomes the authoritative analysis state only after the accepted request/user write commits.

The planned application orchestrator is called `AnalyzeService` in the Gate A plan. That is a target role, not a claim that `backend_lite/app/application/analyze_service.py` exists today. Renaming or evolving `AgentRuntime` must leave one orchestrator, not create parallel old/new pipelines.

## Pipeline boundary

### Entry boundary

The pipeline accepts only a request that has passed the public request schema and semantic admission checks. Before any chat, request, or message write:

- `question`, `session_id`, `chat_id`, `user_type`, and `language` follow the frozen request contract;
- an existing chat is resolved only within the supplied `session_id` ownership boundary;
- a missing, deleted, or foreign-session chat is indistinguishable as `chat_not_found`;
- a new-chat request has a valid non-empty session; and
- an idempotency fingerprint is computed from the canonical accepted request, not from semantically normalized text.

Validation and ownership failure are terminal and have no request/message persistence side effect. How the public request carries an idempotency key is an owner decision recorded below; the current public request has no client-provided `request_id`.

### Execution boundary

One admitted request has exactly one current attempt and one `AnalysisState`. Each stage:

- has a declared precondition and postcondition;
- reads only fields produced by earlier stages and approved immutable providers;
- produces only its owned typed result; `AnalyzeService` validates and applies that result to `AnalysisState`;
- records one bounded transition result;
- cannot insert, remove, repeat, or reorder stages dynamically; and
- cannot commit persistence except at an explicit application/storage boundary.

Stages may choose data values and terminal response modes. They may not choose the stage graph.

### Exit boundary

There are only four externally observable terminal classes:

1. a newly completed, stored successful response;
2. a replay of a previously stored complete response;
3. a frozen public error envelope for an admitted request that cannot complete; or
4. a proposed idempotency/concurrency result whose exact public mapping requires owner approval.

No background reasoning, tool call, persistence mutation, or response revision continues after the terminal result. The stored assistant content must be the guarded/finalized content rendered by chat reload; raw drafts are never persisted as the assistant message.

## Stage contracts and allowed transitions

The identifiers below are architectural stage names. Final Python enum/class names may be selected during implementation review, but their order and responsibility may not be collapsed in a way that removes a boundary.

| Stage | Required input | Authoritative output | Allowed next transition |
| --- | --- | --- | --- |
| `VALIDATE` | raw public payload | accepted immutable request or public validation error | `OWNERSHIP` or terminal error |
| `OWNERSHIP` | accepted request | authorized existing-chat identity or authorized new-chat intent | `IDEMPOTENCY` or terminal `chat_not_found` |
| `IDEMPOTENCY` | authorized identity + canonical fingerprint | new/retry admission, stored replay, in-progress result, final stored error, or key-reuse conflict | `PERSIST_ACCEPTED`, terminal replay/error/in-progress |
| `PERSIST_ACCEPTED` | new/retry admission | committed request record and exactly one user message | `ACTIVATE_STATE` or terminal retryable/final error |
| `ACTIVATE_STATE` | accepted request identity + durable admission result | fresh `AnalysisState` with version stamps/independent trace plus deterministic `normalized_input` and detected language derived from the immutable accepted input | `SAFETY` |
| `SAFETY` | exact current turn + normalized current-turn form | `SafetyResult`: harmful intent, legal high-risk signals, flags, constraints | `MINIMAL_CONTEXT` or terminal infrastructure error |
| `MINIMAL_CONTEXT` | authorized chat + safety result | current question, last assistant clarification, last confirmed topic only | `ROUTING` or terminal store error |
| `ROUTING` | normalized input + safety + bounded context | backend route/domain candidates and risk factors | `LEXICAL_RETRIEVAL` |
| `LEXICAL_RETRIEVAL` | route + bounded retrieval query + corpus version | bounded lexical retrieval result | `EVIDENCE_SELECTION` or terminal `retrieval_error` for a broken store |
| `EVIDENCE_SELECTION` | retrieval result + safety/routing constraints | approved `EvidenceBundle`; healthy no-match is an empty bundle | `DECISION` |
| `DECISION` | safety, route, facts, and evidence sufficiency | authoritative backend domain, risk level, decision, and plan mode | `ANSWER_PLAN` |
| `ANSWER_PLAN` | authoritative decision + selected evidence | deterministic, backend-owned `AnswerPlan` | `RENDER` |
| `RENDER` | `AnswerPlan` | deterministic wording draft; no authoritative field changes | `GUARDS` |
| `GUARDS` | draft + plan + evidence + decision | schema result, structural evidence result, output-safety result, and guarded draft | `FINALIZE` or terminal final error |
| `FINALIZE` | guarded draft + authoritative state | one fully validated `AnalyzeResponse` candidate with backend-owned fields | `PERSIST_COMPLETE` or terminal final error |
| `PERSIST_COMPLETE` | validated response | one assistant message, stored response payload, request `COMPLETE` in one short transaction | `RETURN` or terminal retryable/final error |
| `RETURN` | committed complete record | exact new or stored response | terminal success |

Normalization/language detection is a pure, bounded activation operation, not an additional dynamic stage. It runs while `ACTIVATE_STATE` constructs the initial state, preserves `raw_input`, and cannot classify safety/domain/risk/decision. This keeps the locked `AnalysisState -> SAFETY` transition while ensuring `SAFETY` receives its declared normalized form.

The guard stage is bounded. An output-safety guard may replace a draft with one canonical deterministic refusal/escalation draft, and an evidence guard may remove structurally invalid references or force cautious deterministic content. This is not a regeneration loop. The replacement is validated once; if it remains invalid, the attempt fails without persisting an assistant message.

An infrastructure failure during analysis does not jump directly to `RETURN`. It transitions through the idempotent request failure operation defined by ADR-007 so the durable request becomes `FAILED_RETRYABLE` or `FAILED_FINAL`. A later client retry may start a new attempt only through `IDEMPOTENCY`; no analysis stage retries itself recursively.

## Invariants

**DECIDED:** every implementation of this pipeline must enforce all of the following:

- At most one stage is active for an `AnalysisState` at a time.
- Current-turn unsafe intent has priority over prior context; prior safe turns cannot weaken it.
- Context is same-chat and ownership-checked; no cross-chat or cross-session content enters analysis.
- Gate A context is bounded to the current question, last assistant clarification, and last confirmed topic. It is not the current `SameChatContextBuilder` eight-message raw-history expansion.
- A healthy no-source result is data, not `retrieval_error`; an unavailable or invalid corpus is an infrastructure error.
- Retrieval candidates do not become API sources until backend evidence selection.
- `domain`, `risk_level`, `decision`, `confidence`, `sources`, `safety_notice`, all IDs, and metadata are backend-owned.
- Rendering cannot add advice, elevate strength, invent a plan point, choose evidence, or change authoritative fields.
- Guards consume the authoritative plan/evidence/decision and the current rendered draft; they never trust an earlier response snapshot.
- Safety/evidence guard overrides are escalation/caution only. No guard downgrades a refusal, high-risk classification, or required caution.
- Final response validation occurs before assistant persistence.
- User and assistant exactly-once semantics are enforced by idempotent persistence, not by random message IDs or frontend submit blocking.
- Database transactions are short; no transaction remains open during retrieval, planning, rendering, or guarding.
- A stage trace contains redacted operational facts, never hidden chain-of-thought or full user text by default.
- The stage graph is versioned. The same accepted input, bounded context, corpus/policy/retriever versions, and deterministic generator mode produces the same Gate A plan and response content, apart from backend-generated identifiers and timestamps.

## Prohibited autonomous behavior

The MVP must not:

- create or revise a user goal beyond answering the accepted request;
- make an unbounded plan, reflection, critique, or retry loop;
- discover, select, or invoke arbitrary tools;
- access the web, filesystem, shell, another backend, or an external action provider as an analysis choice;
- mutate the legal corpus, safety policy, configuration, prompts, cases, or its own stage graph;
- spawn sub-agents, background work, or follow-on requests;
- infer permission to act for the user, contact a person/authority, submit a form, or alter evidence;
- use another request's in-memory state or another chat's history;
- allow a model to skip guards or request a more permissive re-run; or
- expose hidden reasoning as trace or metadata.

Adding an explicitly approved, narrow provider adapter at a later gate does not change these rules. The application service remains the fixed orchestrator, and providers remain passive ports with bounded inputs and outputs.

## Gate A boundary

**DECIDED:** Gate A implements one vertical slice using the existing 26 approved snippets and the existing public API semantics. It includes validation/ownership, idempotent persistence, request-scoped state, current-turn safety, minimal context, deterministic routing, lexical retrieval, evidence selection, authoritative decision, deterministic plan and deterministic generation/rendering, guards, finalization, reload-equivalent persistence, trace/version stamps, and evaluation reporting.

Gate A explicitly excludes:

- LLM classification or generation;
- embeddings, vector storage, hybrid lexical/vector retrieval, or semantic reranking;
- corpus expansion;
- full raw-history memory, cross-chat memory, or long-term profile memory;
- autonomous tools/actions;
- production authentication; and
- a requirement to make every current `backend_lite` MVP evaluation case green.

Gate A must run frozen legacy, smoke, and the reviewed MVP selection and report exact failures. It must not weaken cases, policies, or thresholds to make the fallback backend pass.

## Later gates

- **Gate B:** may improve current-turn safety/high-risk coverage and resolve the known reviewed blocker cases. It may not transfer decision authority to a model or collapse current-turn safety into context.
- **Gate E:** may expand context and topic-switch handling after a separate bounded-context contract and tests. It may not introduce full-history authority implicitly.
- **Gate F:** may add an LLM wording adapter behind the generator port. The model receives an allowed `AnswerPlan` and returns wording tied to allowed point IDs; it cannot create advice, sources, decisions, IDs, confidence, notice, or metadata. Deterministic rendering remains the fallback.
- **Later retrieval promotion:** embeddings/hybrid retrieval require the reviewed benchmark and promotion decision in ADR-005. They are not a reason to alter the application stage graph.

Every later gate remains a bounded pipeline revision. None converts the product into an autonomous agent.

## Consequences and trade-offs

### Positive consequences

- Execution is inspectable, testable stage by stage, and reproducible for Gate A.
- Authority and persistence points are explicit; partial writes and duplicate retries can be reasoned about independently from legal analysis.
- The existing fallback implementation can migrate incrementally from `AgentRuntime`, `AgentState`, service classes, and stores instead of being rewritten beside a second stack.
- LLM or retriever upgrades can be introduced behind narrow ports without changing API ownership or the stage graph.
- Faults have defined terminal behavior; a high aggregate evaluation score cannot hide a broken boundary.

### Costs and limitations

- More internal types and transition tests are required than in the current sequential method.
- Deterministic Gate A wording and lexical retrieval will remain less flexible than an LLM/embedding design.
- A strict minimal-context slice will miss some legitimate topic switches and long-thread references until a later gate.
- Exactly-once observable behavior under SQLite requires explicit request records and careful short transactions; it is not provided by the current `messages` primary key alone.
- Structural grounding and a bounded stage trace improve enforceability but do not certify legal correctness.

## Rejected alternatives

### Autonomous agent or planner

Rejected because the product has a fixed request goal, fixed response contract, no approved arbitrary tools, and legal/safety authority that must remain deterministic and inspectable. An autonomous loop adds failure modes without an MVP requirement.

### Preserve `AgentRuntime` semantics and only rename it

Rejected because the current code lacks idempotency, evidence selection/plan boundaries, typed state trace, minimal context, and explicit durable failure transitions. A class rename would not implement the decision.

### Build a second target pipeline beside the current runtime

Rejected because two analyze orchestrators would create behavior drift and an ambiguous source of truth. Gate A should evolve or replace the current anchors behind the same route/composition boundary.

### Let stages call concrete SQLite/provider adapters directly

Rejected because it hides persistence and retry boundaries inside business stages and prevents deterministic fault tests. Concrete adapters belong only in composition wiring.

### Keep a database transaction open for the whole request

Rejected because retrieval/rendering/guards must not hold SQLite locks. The idempotency/request record provides recovery across two short transactions.

### Use the frontend's in-flight button as duplicate protection

Rejected because multi-tab, retry, timeout, and concurrent clients bypass it. Exactly-once observable behavior is a backend responsibility.

### Add LLMs or embeddings in Gate A to improve evaluation results

Rejected because Gate A is an architecture and reliability slice. Model/vector dependencies would obscure the persistence, authority, and state boundaries that Gate A is intended to establish.

## Unresolved owner decisions

| Item | Status | Why it is not silently resolved here |
| --- | --- | --- |
| Public idempotency input: add a distinct idempotency field/header or explicitly change public ID authority | **OWNER_DECISION_REQUIRED** | Resolve before Gate A code changes the request contract. Prefer a distinct carrier mapped to a backend-generated `request_id`; a client-chosen public response ID conflicts with locked backend-ID authority unless separately approved. |
| HTTP/error mapping for in-progress, reused-key, and stored-final-error outcomes | **OWNER_DECISION_REQUIRED** | `REQUEST_IN_PROGRESS` and `IDEMPOTENCY_KEY_REUSED` are not frozen API error codes. |
| Whether to rename `AgentRuntime`/`AgentState` immediately or retain compatibility aliases during the migration | **PROPOSED** | Naming does not change the locked bounded semantics, but it affects review and rollback size. |
| Whether stage names are persisted as a versioned enum or only emitted through a trace sink | **PROPOSED** | Operational compatibility and migration cost need owner/operations review. |
| Bilingual unsupported-language ordering after Gate A | **DEFERRED** | Gate A preserves the already-decided frozen Vietnamese-only behavior; future bilingual safety requires a separate decision. |
| Trace retention and exposure in public `metadata` | **OWNER_DECISION_REQUIRED** | The current backend exposes phase names in metadata, while the target requires redacted operational trace and no full state persistence. |
| Expansion beyond minimal context and exact topic-switch semantics | **DEFERRED** | Gate E work must not block the Gate A reliability slice. |

## Review readiness

This ADR is implementation-ready at the decision level when reviewed together with ADR-002, ADR-003, ADR-004, and ADR-007. Coding must not start on a public idempotency shape until the corresponding owner decisions are recorded.
