# ADR-002: Analysis State and Truth Authority

- **Status:** PROPOSED — ready for architecture review; planning-only
- **Scope:** one analyze execution, its runtime state, durable records, public contract, evidence corpus, and operational trace
- **Depends on:** `docs/api_contract.md`, `docs/ai_core_spec.md`, `docs/rag_spec.md`, `docs/safety_policy.md`, ADR-001, ADR-004, ADR-006, ADR-007
- **Supersedes:** the informal use of mutable locals or a database row as interchangeable “state”; it does not authorize a database migration

## Decision markers

- **DECIDED:** locked by the approved architecture direction or frozen MVP semantics.
- **PROPOSED:** a reviewable internal design choice.
- **OWNER_DECISION_REQUIRED:** must be resolved before dependent implementation.
- **DEFERRED:** outside Gate A.

## Context and problem

The current fallback pipeline already carries most intermediate values in `backend_lite/app/runtime/agent_state.py::AgentState`. It is composed from:

- `RequestState`;
- `ChatState`;
- `ClassificationState`;
- `RetrievalState`;
- `GenerationState`;
- `GuardState`;
- `PersistenceState`;
- `TraceState`; and
- an untyped `final_response`.

This is a credible migration anchor, not the target contract. Several authority domains are mixed together:

- normalization, language, safety facts, route, risk, and decision all live in `ClassificationState`;
- retrieval candidates and selected API source objects share `RetrievalState`;
- policy stages receive or mutate the whole `AgentState` instead of returning narrow typed results;
- `TraceState` contains only phase names, warnings, errors, and elapsed milliseconds;
- there is no `AnswerPlan`, `EvidenceBundle`, version-stamp object, typed final response, request status, or recovery identity; and
- the current response metadata includes a partial phase-name trace, so that partial trace is indirectly stored inside the assistant `content_json`, even though no explicit trace persistence policy exists.

The SQLite store currently has only `chats` and `messages`. It has no durable analysis-request record. A process crash therefore loses all in-memory state and cannot distinguish a safe retry from a duplicate request. Conversely, persisting the whole runtime object would retain unnecessary user/context/draft data, couple recovery to every internal model revision, and blur the distinction between tentative and committed truth.

The architecture needs explicit truth categories and an internal state contract before Gate A code can be divided into ports, stages, persistence records, and tests.

## Decision: four distinct sources of truth

**DECIDED:** VietLaw-Chat recognizes exactly four source-of-truth categories for this workflow.

| Truth category | Authority | Lifetime | What it proves | What it does not prove |
| --- | --- | --- | --- | --- |
| `AnalysisState` | authoritative in-memory state for one accepted analysis execution | one process attempt only | the current attempt's typed intermediate and final values | durable completion, source legal correctness, or public schema approval |
| Persistence records | durable truth after the relevant transaction commits | across process restarts | accepted request/user write, request status, stored final response, assistant write | that an uncommitted in-memory value existed or was correct |
| Contract artifacts | machine-enforced API shape truth | versioned across releases | allowed/required public fields, enums, and validation shape | legal/product semantics beyond the artifact or runtime evidence correctness |
| Legal corpus | retrievable evidence identity/content truth | versioned corpus release | approved source IDs and source fields that retrieval may select | legal correctness, applicability, entailment, or a legal outcome |

`docs/api_contract.md` remains the normative product-semantics document. ADR-006 defines the relationship between that document and planned shared OpenAPI/JSON Schema artifacts. The repository currently has no `contracts/openapi.json` or `contracts/generated/*.schema.json`; this ADR does not pretend otherwise. Until shared artifacts are created and reviewed, backend-local Pydantic models are implementation schemas, not a substitute for the planned cross-backend machine contract.

`data/legal_snippets.json` is the current runtime corpus and contains 26 active records. A corpus match establishes identity and faithful source fields only. Neither `AnalysisState.evidence_bundle` nor a green source oracle certifies that the source supports a legal claim.

## Truth precedence and commit rules

The categories are complementary rather than interchangeable:

1. During an active attempt, `AnalysisState` is authoritative for tentative analysis values.
2. After Transaction A commits, the durable request record and persisted user message are authoritative for admission and exactly-once user persistence.
3. After Transaction B commits, the durable `COMPLETE` record, stored response payload, and assistant message are authoritative. If a process-local object disagrees after that commit, durable records win.
4. A new response may be returned only from the validated response that Transaction B commits, or from the exact stored complete response on replay.
5. Contract validation constrains both the candidate response before commit and the stored response on replay. Runtime state cannot add public fields outside the approved artifact.
6. Source objects are copied only from the selected records of the versioned legal corpus. Conversation history, a generated draft, metadata, and model output are never legal evidence truth.
7. On any drift between normative semantics and machine artifacts, the build/release is blocked for contract review. Runtime code must not choose whichever version is convenient.

## `AnalysisState` contract

**DECIDED:** one admitted execution attempt has one fresh `AnalysisState`. It is never global, never shared across requests, and never reused for a retry attempt.

The required field design is:

```text
AnalysisState
├── request_identity
├── raw_input
├── normalized_input
├── conversation_context
├── safety_result
├── route_candidates
├── retrieval_results
├── evidence_bundle
├── decision
├── answer_plan
├── generated_draft
├── guard_results
├── final_response
├── version_stamps
└── trace
```

The architecture label `stage_trace` in planning discussions is represented by the concrete field name `trace`; there must not be two independent trace lists. The model declaration must contain this exact independent-default pattern:

```python
trace: list[StageTrace] = Field(default_factory=list)
```

Using `[]` as a class/model default is prohibited because it risks shared mutable state. A new state must start with a trace list that is identity-distinct from every other request's list.

### Field design and authority

| Field | Minimum Gate A contents | Sole writer | Invariant |
| --- | --- | --- | --- |
| `request_identity` | durable request-row identity, public `request_id`, `session_id`, resolved `chat_id`, durable user-message ID, optional attempt-local assistant candidate/committed assistant ID, request fingerprint, attempt number | application admission/orchestrator | IDs are backend-owned; the finalizer returns a typed candidate that the orchestrator applies; no assistant ID is durable before the successful completion transaction under the proposed schema; idempotency key shape remains an owner decision |
| `raw_input` | canonical accepted public payload plus the exact accepted question string before semantic normalization | admission/orchestrator | never reconstructed from normalized text; no secrets are added |
| `normalized_input` | trimmed/space-normalized, lowercase/punctuation-normalized, and accent-insensitive forms needed by deterministic policies | normalizer result applied by orchestrator | original input remains unchanged; normalization cannot alter persisted user text |
| `conversation_context` | current question, last assistant clarification, last confirmed topic, and provenance selected after safety from assistants strictly before the durable current-user ordering cutoff | minimal-context stage | same authorized chat only; Tx A/Tx B assign strictly increasing per-chat message timestamps inside serialized writes, so later completion cannot enter the cutoff; no full raw history in Gate A |
| `safety_result` | current-turn harmful-intent flag/category, legal high-risk signals, matched policy codes, safety constraints | `SafetyPolicy` result applied by orchestrator | describes safety facts/constraints; does not choose every legal response |
| `route_candidates` | ordered domain/topic candidates, deterministic match factors, selected route candidate | `RoutingPolicy` result applied by orchestrator | context cannot override current-turn unsafe classification |
| `retrieval_results` | bounded lexical candidates, stable snippet IDs, internal scores/reasons, retrieval status | `Retriever` result applied by orchestrator | candidates come only from the loaded corpus version; scores are not legal confidence |
| `evidence_bundle` | selected approved source records/IDs, evidence adequacy/no-source category, allowed support mapping | evidence-selection result applied by orchestrator | a selected source is a subset of retrieval; source fields reconcile with the corpus |
| `decision` | authoritative domain, risk level, response decision, deterministic reason codes, evidence/fact sufficiency, and backend confidence once calculated | `ResponseDecisionPolicy` and later `ConfidenceCalculator`, through orchestrator | renderer/model cannot write it; guard changes are stricter/cautious only and are recorded |
| `answer_plan` | deterministic ordered backend guidance points and source support links defined by ADR-004 | answer-plan builder result applied by orchestrator | complete allow-list for rendered advice; no unknown point or strength elevation |
| `generated_draft` | Gate A deterministic rendered content; later only allowed point IDs plus wording | generator result applied by orchestrator | no source objects, decision fields, IDs, notice, confidence, or metadata |
| `guard_results` | schema, structural evidence, and output-safety results; guarded content; overrides/warnings | guard results applied by orchestrator | all guards run before finalization; no stale pre-guard authority reaches response |
| `final_response` | typed, schema-valid `AnalyzeResponse` candidate | `ResponseFinalizer` result applied by orchestrator | absent until every required guard passes; exact candidate committed in Transaction B |
| `version_stamps` | contract, corpus, policy, prompt, retriever, and generator versions/mode | application bootstrap at state activation | immutable for the attempt; Gate A prompt is `none`, generator mode is `deterministic` |
| `trace` | ordered `StageTrace` entries | orchestrator's trace recorder | redacted, bounded, no hidden reasoning/full user text by default |

`AnalysisState.final_response` must be typed as the approved internal/public response model or `None`; `Any` is not an acceptable target. Required fields may be modeled as `None` before their producing stage, but every stage transition validates that its predecessor's outputs are present. `None` is not silently treated as an empty source list, a low-risk decision, or a successful guard.

### Mutation boundary

**DECIDED:** `AnalyzeService` is the only component allowed to advance and assign `AnalysisState` fields. A stage or port receives the narrow typed inputs it needs and returns a typed result. It does not receive unrestricted write access to the whole state.

This differs from current methods such as `SameChatContextBuilder.build(state)` and services that read/mutate `AgentState` directly. Gate A should migrate those contracts incrementally; it must not create a second state object and synchronize two mutable authorities.

Each field has a single normal producing stage. Later guards may produce an explicit override record for `decision` or guarded content, but they do not mutate prior safety, route, retrieval, evidence, plan, or draft history. This preserves why the final value changed.

## State lifecycle and transition invariants

The state lifecycle inside one attempt is:

```text
ACTIVATED
  -> SAFETY_RECORDED
  -> CONTEXT_RECORDED
  -> ROUTED
  -> RETRIEVED
  -> EVIDENCE_SELECTED
  -> DECIDED
  -> PLANNED
  -> DRAFTED
  -> GUARDED
  -> FINALIZED
  -> COMMITTED
```

An infrastructure or validation failure transitions to `ATTEMPT_FAILED` through the request store; it does not mutate later fields to plausible defaults. A stored replay does not reactivate the old state: the application returns the durable response directly and may create only a small replay trace/correlation context.

Required invariants include:

- stage order is monotonic and matches ADR-001;
- at most one field-producing stage is active at once;
- no stage reads a downstream field;
- a retry creates a new state with the same durable request identity and incremented attempt, not a resumed Python object;
- a complete request cannot be re-analyzed;
- `final_response` cannot exist before all guard results are present and passing/handled;
- a `COMMITTED` state refers to the durable response payload committed with the assistant message and `COMPLETE` status;
- no caller can observe a partially built assistant response; and
- state fields and trace summaries never contain hidden chain-of-thought.

## Runtime state versus durable and external artifacts

| Artifact | Durable? | Required contents | Explicit exclusions |
| --- | ---: | --- | --- |
| `AnalysisState` | no | all typed per-attempt analysis fields above | cross-request state; long-term memory |
| Persisted request record | yes after commit | session/request identity, fingerprint, status, attempts/error code, stored response, version stamps, timestamps as specified by ADR-007 | whole state, retrieval scores, raw context history, hidden reasoning |
| Persisted user message | yes after Transaction A | one backend ID, authorized chat ID, role/type, exact accepted question, timestamp | normalized replacement text, analysis results |
| Persisted assistant message | yes after Transaction B | one backend ID and the final guarded `AnalyzeContent` subset used by chat reload | raw draft, pre-guard values, unknown source objects |
| Final response payload | yes in the complete request record | full validated response envelope, including backend IDs and metadata | uncommitted/transient values |
| Trace sink | operational destination; durability policy separate | redacted stage transitions and correlation/version fields | full user text by default, raw prompt, private context, chain-of-thought |

The current assistant reload contract must be preserved: its stored `content_json` is the exact 11-field renderable subset of the live response (`domain`, `risk_level`, `decision`, `summary`, `clarifying_questions`, `checklist`, `next_steps`, `sources`, `safety_notice`, `confidence`, `metadata`). Top-level request/chat/message identifiers remain in the response/request record rather than being invented during reload.

## Stage trace design

`StageTrace` is an operational transition record, not a reasoning transcript. Its minimum field design is:

```text
stage
started_at
finished_at
duration_ms
status
input_summary_redacted
output_summary_redacted
error_code
```

Required semantics:

- `started_at` and `finished_at` are UTC timestamps; `duration_ms` is measured with a monotonic clock and is non-negative.
- `finished_at` and `duration_ms` may be absent only while an entry is actively running.
- `status` is one of `started`, `completed`, or `failed` for Gate A.
- input/output summaries contain bounded categories, counts, IDs safe for operations, and booleans—not full question/history/draft text by default.
- `error_code` is a sanitized public or internal operational code, never an exception message containing secrets.
- every started stage is closed as completed or failed in memory, including exception paths; downstream stages that never start have no fabricated trace entry, and a duplicate replay before state activation uses only a bounded correlation event outside `AnalysisState.trace`.
- trace order follows stage start order; duration is diagnostic and does not control policy.
- trace data cannot be used as legal evidence or confidence.

**PROPOSED:** the in-memory list is authoritative for the active attempt; a `TraceSink` receives copies for structured logs. Sink failure adds a bounded warning and must not make a legally safe response less safe. Whether Gate A requires durable trace retention is an owner decision below.

## Gate A persistence boundary

**DECIDED:** Gate A does not persist the whole `AnalysisState`.

Gate A persists only:

- the request/idempotency record required by ADR-007;
- one exact accepted user message;
- one final guarded assistant message on success;
- the complete response payload on success or the approved final error data on failure;
- request status/attempt/error fields;
- required version stamps; and
- bounded operational trace through the chosen sink, not as an opaque state blob.

In particular, Gate A does not persist raw retrieval candidate lists, internal scores, the full minimal context object, the raw generated draft, all guard internals, or the entire trace list in the chat message. Public metadata remains backend-owned and bounded; dumping the state into `metadata` is prohibited.

## Crash and recovery behavior

Recovery reconstructs a fresh attempt; it never deserializes and resumes an arbitrary Python call stack or the full prior `AnalysisState`.

| Crash/failure point | Durable observation | Required recovery behavior |
| --- | --- | --- |
| before validation/ownership/idempotency commit | no accepted request record or message | client may submit normally; no recovery work |
| during Transaction A, including after request insert but before user insert | transaction is uncommitted | rollback leaves neither record nor message externally visible; retry begins normally |
| after Transaction A/user commit, before state activation | request is `PROCESSING`; exactly one user message exists | stale-processing recovery marks/reclassifies it retryable under the approved lease policy; retry creates a fresh state without a new user message |
| during safety/context/routing/retrieval/evidence/plan/render/guards | same `PROCESSING` record and one user message | no mid-stage resume; record retryable/final error when possible; a retry rebuilds state from durable request/user, bounded context, and pinned versions |
| after final response is built but before Transaction B | no assistant/complete response committed | discard memory; deterministic retry may rebuild; do not expose or duplicate the candidate |
| after assistant insert but before `COMPLETE` inside Transaction B | transaction is uncommitted | rollback both assistant and request completion; externally remains retryable/in-progress, with no partial assistant |
| after Transaction B commits but before HTTP response reaches client | request is `COMPLETE`; one assistant and stored response exist | duplicate returns the exact stored response; pipeline is not re-executed |
| process restarts with stale `PROCESSING` records | no live state can be trusted | recovery policy identifies stale attempts, does not assume completion, and permits only the ADR-007 retry transition |

The assistant insert, response payload, and `COMPLETE` update must share one transaction so “assistant inserted but request not complete” is not an observable committed state. This is a target invariant; current `SQLiteChatStore.add_message()` commits each message independently and does not provide it.

If a retry requires an older corpus/policy/retriever version that is no longer available, the backend must not silently claim it resumed the same deterministic execution. Exact version-availability/error behavior is an owner decision.

## Current-to-target migration map

| Current `backend_lite` element | Target state area | Required change, not yet implemented |
| --- | --- | --- |
| `RequestState` | `request_identity`, `raw_input` | add durable request/fingerprint/attempt identity and separate exact input from IDs |
| `ChatState` | `conversation_context` | replace last-eight-message raw expansion with the Gate A three-field context contract |
| `ClassificationState` | `normalized_input`, `safety_result`, `route_candidates`, `decision` | split facts/routes/final authority; remove mixed ownership |
| `RetrievalState` | `retrieval_results`, `evidence_bundle` | separate candidates from selected approved evidence |
| `GenerationState` | `generated_draft` | consume `AnswerPlan`; stop treating source selection as generator authority |
| `GuardState` | `guard_results` plus explicit stricter decision override | retain pre/post values and reason codes; do not overwrite provenance |
| `PersistenceState` | `request_identity` plus durable store result | move status/exactly-once truth to persistence records, not booleans in memory |
| `TraceState` and `_phase()` | `trace: list[StageTrace]` plus `TraceSink` | add timestamps/status/redacted summaries/error code and independent defaults |
| `AgentState.final_response: Any` | typed `final_response` | forbid untyped response state |

The smallest safe migration evolves these anchors behind one orchestrator. It does not duplicate every service under newly named directories in one step.

## Gate A versus later gates

### Gate A

- creates a fresh request-scoped state after durable admission;
- carries only the minimal context contract;
- captures the six required version stamps with `prompt_version = "none"` and `generator_mode = "deterministic"`;
- keeps state in memory and persists only the explicit durable artifacts above;
- emits redacted structured traces;
- rebuilds a fresh state on retry/restart; and
- preserves the existing public response and reload-equivalence shape.

### Later gates

- Gate E may add a separately versioned bounded context summary/topic-switch model; it does not turn chat history into evidence truth.
- Gate F may add an LLM wording draft, but model state/history is not `AnalysisState` authority and is not durable truth unless a future ADR explicitly defines it.
- A future distributed backend may replace SQLite and add durable workflow execution, but it must preserve the four truth categories and commit semantics.
- Long-term personal memory, cross-chat state, checkpointing the whole analysis object, and hidden reasoning persistence are deferred.

## Consequences and trade-offs

### Positive consequences

- Every intermediate value has an explicit owner, producer, and lifecycle.
- Crash recovery is based on durable request/message truth rather than guessed Python state.
- A model/provider cannot acquire authority by returning extra fields.
- Traceability improves without making hidden reasoning or full user text an observability requirement.
- The current `AgentState` investment can be migrated incrementally rather than discarded.

### Costs and limitations

- Typed stage results and transition validation add code and tests.
- Some data is intentionally recomputed after a crash instead of checkpointed.
- Deterministic replay requires version availability and a reviewed stale-processing policy.
- A redacted trace may be less convenient than dumping the full state during debugging.
- This boundary proves structural consistency, not legal correctness.

## Rejected alternatives

### Treat SQLite rows as the live analysis state

Rejected because holding/updating a database workflow row at every reasoning stage would couple domain logic to persistence, increase lock contention, and confuse committed truth with tentative values.

### Persist the complete `AnalysisState` after every stage

Rejected for Gate A because it stores unnecessary raw/context/draft data, creates schema-migration pressure for every internal field change, and invites mid-stage resume complexity without an MVP requirement.

### Keep state in local variables across services

Rejected because it allows stale pre-guard or pre-decision values to reach finalization and makes trace/recovery invariants untestable.

### Give every stage mutable access to the whole state

Rejected because it makes field authority conventional rather than enforceable. Stages return narrow typed results; the orchestrator advances state.

### Put full history in `conversation_context`

Rejected for Gate A because the approved slice is minimal and bounded. Raw history is neither legal evidence nor a substitute for current-turn safety.

### Treat a corpus match as legal truth

Rejected because corpus identity and excerpt faithfulness do not establish applicability, entailment, or legal correctness.

### Expose the full trace in API metadata

Rejected as a default because it can leak user/context data, couples the public response to internals, and is not required by the frozen API semantics.

## Unresolved owner decisions

| Item | Status | Required decision |
| --- | --- | --- |
| Client-visible idempotency identity and its relationship to public `request_id` | **OWNER_DECISION_REQUIRED** | Resolve before finalizing `request_identity` and the request record contract. |
| Stale `PROCESSING` lease/timeout and recovery trigger | **OWNER_DECISION_REQUIRED** | Define when a restart may move a record to retryable without racing a live request. |
| Version retention for deterministic retries | **OWNER_DECISION_REQUIRED** | Decide whether old corpus/policy/retriever versions remain loadable or a version-unavailable attempt becomes final. |
| Trace sink durability, retention, and access control | **OWNER_DECISION_REQUIRED** | Choose structured logs only versus a durable operational store and define retention/redaction review. |
| Public metadata exposure of stage names/version stamps | **OWNER_DECISION_REQUIRED** | Preserve only approved bounded metadata; do not inherit the current `runtime_trace` field accidentally. |
| Exact persisted response representation and canonical JSON form | **OWNER_DECISION_REQUIRED** | Resolve with ADR-007; required for byte/logical replay equivalence and migration compatibility. |
| How clarification/topic provenance is bounded and derived | **OWNER_DECISION_REQUIRED** | Approve strict in-transaction per-chat message timestamps, the durable current-user cutoff, post-safety newest-qualifying selection, recognized-topic rules, retry reuse, and null behavior. |
| Full state checkpoint/resume | **DEFERRED** | Not required for the SQLite Gate A vertical slice. |

## Review readiness

This ADR is ready for review as a state-authority decision. It authorizes no model, port, table, migration, or code by itself. Gate A implementation should not begin until the public idempotency identity and stale-processing recovery decisions are approved together with ADR-007.
