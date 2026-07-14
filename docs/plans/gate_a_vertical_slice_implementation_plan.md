# Gate A vertical-slice implementation plan

**Status:** planning only

**Prepared:** 2026-07-13

**Target:** `backend_lite` fallback backend

**Decision dependencies:** ADR-001 through ADR-007

**Implementation authority:** none granted by this document

## 1. Outcome and boundaries

Gate A is a bounded, state-first legal-navigation pipeline. It is not an autonomous agent, a tool-using loop, a TOMTIT implementation, or a general legal-reasoning platform. Its purpose is to make one deterministic `/api/analyze` vertical slice explicit, recoverable, inspectable, and safe enough to evaluate against the existing corpus and contracts.

The implementation sequence is:

> validation -> ownership -> idempotency -> persist valid request and one user message -> `AnalysisState` -> safety -> minimal context -> routing -> lexical retrieval -> evidence selection -> authoritative decision -> deterministic `AnswerPlan` -> deterministic generation/rendering -> schema/evidence/output guards -> finalization -> persist one assistant message -> response

Gate A uses the 26 currently active records in `data/legal_snippets.json`. It does not add or rewrite corpus records. It uses no LLM, embedding, vector store, hybrid retrieval, NLI model, authentication system, full-history memory, external tool, or shared business-logic package with the primary backend. The backend remains authoritative for domain, risk, decision, confidence, sources, safety notice, identifiers, and metadata. Generation renders a backend-approved plan; in Gate A it is deterministic and may not alter those decisions.

This plan does not require the MVP evaluation gate to become green. It requires the implementation to run legacy, smoke, and MVP evaluation, record the exact pass/fail/blocker result, and avoid hiding failures. Known safety/evaluator remediation outside this vertical slice remains Gate B work unless a Gate A output guard is needed to prevent a regression.

## 2. Current repository map and migration posture

The current `backend_lite` path is a working deterministic implementation, but its control flow and persistence are coupled:

| Current path | Current responsibility | Gate A implication |
|---|---|---|
| `backend_lite/app/main.py` | Creates FastAPI, calls `build_container`, registers middleware/handlers/routes. | Keep as bootstrap and composition root; no policy logic. |
| `backend_lite/app/dependencies.py` | Instantiates concrete SQLite/JSON stores, every policy/service, and `AgentRuntime`. | Transitional wiring is moved into or called only by the composition root. Concrete adapters must not leak into the application service. |
| `backend_lite/app/api/routes_analyze.py` | Passes a validated `AnalyzeRequest` directly to `container.runtime.analyze`. | Route remains thin and calls `AnalyzeService`; request-id transport is blocked on contract-owner choice. |
| `backend_lite/app/runtime/agent_runtime.py` | Runs 18 mutable phases and directly knows store, classifiers, retriever, generator, guards, response builder, IDs, and time. | Replace as the analyze use-case authority with the bounded `AnalyzeService`; retain temporarily as a parity/rollback path only. |
| `backend_lite/app/runtime/agent_state.py` | Dataclass aggregate with request/chat/classification/retrieval/generation/guard/persistence/trace state. | Supersede with typed Pydantic internal contracts; do not persist this aggregate wholesale. |
| `backend_lite/app/runtime/protocols.py` | Broad `Protocol` set, many `Any` values, and a CRUD-oriented `ChatStore`. | Introduce use-case-shaped effect ports in `application/ports.py`; do not merely move the `Any` protocols. |
| `backend_lite/app/stores/sqlite_chat_store.py` | Initializes `chats`/`messages`; each create/add operation is a separate short transaction. | Preserve chat reads/CRUD and add an adapter with atomic `begin_request`, `complete_request`, `fail_request`, and `load_bounded_context` operations. |
| `backend_lite/app/services/context_builder.py` | Loads up to eight messages and converts much of the prior conversation into retrieval terms. | Replace for analyze with the strict minimal-context contract; do not feed full history to routing/retrieval. |
| `backend_lite/app/services/input_normalizer.py`, `language_detector.py` | Deterministically produce normalized/accentless forms and frozen Vietnamese/unsupported classification. | Preserve as migration anchors behind a typed pure activation helper; activation populates `normalized_input` before safety without adding a dynamic stage. |
| `backend_lite/app/services/chat_title.py` | Produces a deterministic question-derived title (topic optional, but current runtime calls it before topic routing). | Keep as a pure admission collaborator; `AnalyzeService` passes a backend-authored title in `BeginRequest` for new chat, and the store never invents title metadata. |
| `backend_lite/app/services/rag_retriever.py` | Keyword scoring, topic/source allowlists, domain filtering, source-type boost, top-k selection. | Port the behavior into a deterministic lexical adapter, make score/threshold/dedupe artifacts explicit, and establish a benchmark baseline before tuning. |
| `backend_lite/app/services/unsafe_detector.py` | Pattern-based current-turn safety/high-risk detection and sometimes suggests an expected decision. | Safety may classify harmful intent and high-risk facts, but may not directly own the normal response decision. |
| `backend_lite/app/services/domain_classifier.py`, `risk_classifier.py`, `decision_policy.py` | Mutate/consume the current runtime aggregate and jointly determine route/risk/decision. | Re-express as pure typed pipeline stages with the ADR-003 authority chain. |
| `backend_lite/app/services/lite_content_generator.py` | Deterministic topic-specific prose/checklists and copied source IDs. | Split plan construction from rendering; stable point IDs and evidence links exist before prose. |
| `backend_lite/app/guards/citation_guard.py` | Removes source IDs outside retrieval and cautions some unsupported strong claims. | Replace with structural evidence-plan enforcement; do not claim automated legal correctness. |
| `backend_lite/app/guards/safety_guard.py` | Scans output and can overwrite domain, risk, and decision. | Output safety remains a guard, while authoritative final values come through the decision policy/finalizer chain. |
| `backend_lite/app/services/response_builder.py` | Calculates confidence, selects sources, assembles metadata and response. | Split `ConfidenceCalculator` and `ResponseFinalizer`; finalizer is the only response assembler. |
| `backend_lite/app/schemas/api.py` | Frozen v1 request/response models. Request has no `request_id`; response creates one. | Idempotent retries cannot be guaranteed across HTTP attempts until the owner chooses an input key transport and updates normative artifacts. |
| `backend_lite/tests/` | Flat unit/integration suite for current contract, RAG, safety, sessions, chat, reload, and frontend consistency. | Preserve all current tests and add focused unit/integration/contract/evaluation tests listed below. |

There is currently no repository-root `contracts/` directory and no `backend_lite/app/application/`, `contracts/`, `pipeline/`, `adapters/`, or `observability/` package. These are planned additions, not descriptions of existing code. `data/vietlaw_chat.sqlite3` and `*.db`/`*.sqlite`/`*.sqlite3` are ignored by `.gitignore`; the implementation must never rely on a developer's existing ignored database or delete it as a migration strategy. Tests use a temporary SQLite file.

The smallest safe migration is additive and staged. New typed code coexists with `AgentRuntime` while isolated tests are built. The route is switched to `AnalyzeService` only after current contract/reload/session tests pass. The old runtime can remain unreachable for one rollback window, then be removed in a separate cleanup after Gate A evidence is accepted. No primary-backend module is imported.

## 3. Dependency direction and ports

The intended dependency direction is:

```text
FastAPI route / main composition root
                 |
                 v
       application.AnalyzeService
          |                 |
          v                 v
 typed internal contracts   pure pipeline policies
          ^                 ^
          |                 |
 ports <---------------- adapters (SQLite, JSON lexical, trace sink)
```

The application layer knows typed ports and typed internal contracts, not SQLite, JSON files, FastAPI, or concrete classifiers. Pipeline stages are pure functions or deterministic policy objects. Adapters implement side effects. `main.py` is the only production composition root; route modules only obtain and invoke the already-wired service.

`backend_lite/app/application/ports.py` defines at least:

```python
class ChatStore(Protocol):
    def begin_request(self, command: BeginRequest) -> BeginRequestResult: ...
    def complete_request(self, command: CompleteRequest) -> StoredResponse: ...
    def fail_request(self, command: FailRequest) -> None: ...
    def load_bounded_context(self, query: BoundedContextQuery) -> MinimalConversationContext: ...

class Retriever(Protocol):
    def retrieve(self, query: RetrievalQuery) -> RetrievalResult: ...

class AnswerGenerator(Protocol):
    def generate(self, plan: AnswerPlan) -> AnswerDraft: ...

class TraceSink(Protocol):
    def record_transition(self, event: StageTrace) -> None: ...

class Clock(Protocol):
    def now_utc(self) -> datetime: ...
    def monotonic(self) -> float: ...

class IdGenerator(Protocol):
    def new_id(self, kind: IdKind) -> str: ...
```

`ChatStore.begin_request` is not a synonym for `add_message`. It owns the short transaction that resolves a new/duplicate/retry request and, for a new request only, creates the request record and inserts exactly one user message. `complete_request` atomically inserts exactly one assistant message, stores the exact API outcome, and moves the request to `COMPLETE`. `fail_request` performs a short failure transaction. `load_bounded_context` receives the durable current user-message ID as an ordering cutoff and returns the bounded DTO defined in section 8, never arbitrary message history.

These six protocols are the minimum recommended boundary. The first four isolate required storage, retrieval, generation, and observability effects. `Clock` and `IdGenerator` remain separate because time, deadlines, durations, and backend-owned identifiers must be deterministic in tests and must not be imported as globals by the pipeline. `AnalyzeService` receives all required ports through its constructor. Pure policies remain typed collaborators, not I/O ports.

`main.py` constructs one `SystemClock` and one `PrefixedUuidIdGenerator`. The same clock is injected into `AnalyzeService`, the new SQLite adapter, and trace helper; the adapter uses it only while holding short write transactions to assign strict per-chat message timestamps. New Gate A `application/**`, `pipeline/**`, `adapters/sqlite_store.py`, observability, and switched error-handler code do not import `datetime.now`, `time.monotonic`, or `uuid4` directly. Existing non-analyze chat CRUD may retain legacy helpers during the rollback window, but the Gate A analyze path never delegates ID or message-timestamp creation to that legacy store; migrating the remaining CRUD helpers is separate compatibility cleanup.

Before `begin_request`, `AnalyzeService` obtains backend request/user and, for a new-chat command, chat candidate IDs from `IdGenerator`. It also calls the existing deterministic `ChatTitleService.make(accepted_question)` and includes the backend-authored title in `BeginRequest`; topic routing has not happened yet, so no future topic result is used. The SQLite adapter atomically adopts those candidates/title only when it wins creation of a new carrier row; a duplicate/retry returns stored identity/title and discards unused candidates. The store never generates IDs or business titles, and a losing caller never overwrites durable metadata.

Pure `SafetyPolicy`, `RoutingPolicy`, `ResponseDecisionPolicy`, `ConfidenceCalculator`, evidence selector, plan builder, and `ResponseFinalizer` need not become I/O ports. They are constructor-injected typed collaborators where substitution helps tests, but the design must not create one port per pure function merely to imitate dependency inversion.

## 4. `AnalysisState` contract and authority

`backend_lite/app/contracts/state.py` defines one Pydantic `AnalysisState`. Its top-level fields are:

| Field | Typed content | Authority/lifetime |
|---|---|---|
| `request_identity` | backend request/session IDs, optional carrier digest/version, requested and resolved chat IDs, durable user-message ID, optional attempt-local assistant candidate ID, committed assistant ID when complete, request fingerprint, contract version | `AnalyzeService` applies validation/idempotency/finalization results; public IDs are backend-authoritative, raw carrier is not retained, and no assistant ID is durable before Tx B. |
| `raw_input` | validated question, user type, requested language | `AnalyzeService` assigns the accepted command; current request only, no cross-chat content. |
| `normalized_input` | boundary-trimmed question, normalized/accentless forms, detected language | Normalizer returns a typed result; `AnalyzeService` applies it. |
| `conversation_context` | current question plus only last assistant clarification and last confirmed topic | Context port/policy returns a bounded typed result; `AnalyzeService` applies it after safety. |
| `safety_result` | harmful-intent flag/category, legal high-risk flags, matched policy IDs, safe-current-turn marker | `SafetyPolicy` produces the typed result; `AnalyzeService` applies it, and it does not set every response decision. |
| `route_candidates` | typed domain/topic candidates with deterministic scores/reasons | `RoutingPolicy` produces; `AnalyzeService` applies. |
| `retrieval_results` | ranked lexical hits with source IDs, scores, rank, matching metadata, retrieval version | `Retriever` produces; `AnalyzeService` applies; candidates are not yet approved evidence. |
| `evidence_bundle` | selected approved source records and allowed source IDs per guidance point | Evidence selector produces; `AnalyzeService` applies. |
| `decision` | authoritative domain, risk, response decision, confidence inputs, reason codes | `ResponseDecisionPolicy` and `ConfidenceCalculator` produce typed results in order; `AnalyzeService` applies them. |
| `answer_plan` | ordered, typed guidance points and presentation slots | Deterministic plan builder produces; `AnalyzeService` applies. |
| `generated_draft` | ordered rendered points and no authoritative classification fields | Deterministic `AnswerGenerator` produces; `AnalyzeService` applies. |
| `guard_results` | schema, evidence, and output-safety results; removals/replacements/reasons | Guards produce typed results; `AnalyzeService` applies them. |
| `final_response` | validated v1 response or `None` until finalization | `ResponseFinalizer` produces a typed candidate; `AnalyzeService` alone assigns it. |
| `version_stamps` | contract, corpus, policy, prompt, retriever, generator versions | `AnalyzeService` captures them at begin; the store persists the approved subset. |
| `trace` | `list[StageTrace]` | `AnalyzeService` records redacted transitions; this is the concrete field for architectural `stage_trace`. |

The mutable-list default must be safe and explicit:

```python
class AnalysisState(BaseModel):
    # ...fields above...
    trace: list[StageTrace] = Field(default_factory=list)
```

Thus the required trace buffer is exactly `trace: list[StageTrace] = Field(default_factory=list)`, reached as `state.trace`. The planning label `stage_trace` does not create a second field or nested trace collection. No list, dict, or nested model uses a mutable literal default.

The four sources of truth are not interchangeable:

1. `AnalysisState` is transient execution truth for one attempt.
2. SQLite is durable request/message/outcome truth.
3. `docs/api_contract.md`, future `contracts/openapi.json`, and generated schemas are external API-shape truth.
4. `data/legal_snippets.json` is approved evidence truth, not a response or policy store.

State activation calls the typed pure normalization helper over `raw_input`, then `AnalyzeService` applies normalized/accentless forms and detected language to `normalized_input` before starting `SAFETY`. This is part of `ACTIVATE_STATE`, not a reorderable stage or trace loop; it preserves the exact raw accepted question and cannot produce safety, route, risk, decision, or evidence values.

The complete `AnalysisState` must not be serialized into SQLite, response metadata, or logs. Durable storage contains request identity/status, one user message, one assistant message if complete, exact completed/final-error outcome, error classification, version stamps, and timestamps. A retry reconstructs state from the stored request record, stored user message, bounded same-chat context, and the exact stamped corpus/policy/generator versions. If a required stamped artifact is no longer available, recovery must fail explicitly rather than silently run a different version; artifact-retention duration is an owner decision before cleanup automation.

## 5. Authoritative decision flow

The authority chain is fixed:

> `SafetyPolicy` -> `RoutingPolicy` -> `ResponseDecisionPolicy` -> `ConfidenceCalculator` -> `ResponseFinalizer`

- `SafetyPolicy` classifies harmful intent, current-turn unsafe instructions, and serious legal/high-risk facts. Harmful intent can justify refusal. Legal high risk without harmful intent normally justifies escalation/cautious guidance, not refusal. Insufficient evidence is neither harmful intent nor automatically high risk.
- `RoutingPolicy` proposes domain/topic from current input and allowed minimal context. It cannot weaken a harmful-current-turn result.
- `ResponseDecisionPolicy` owns the final `decision`, domain, and risk choice using safety, route, and evidence adequacy. It distinguishes `refuse_unsafe_request`, `recommend_professional_help`, cautious no-source/clarifying guidance, ordinary guidance, and unsupported.
- `ConfidenceCalculator` uses deterministic inputs (route margin, evidence adequacy, guard changes) and cannot increase confidence after evidence/output guards remove content.
- `ResponseFinalizer` assembles the response using backend-authoritative IDs, values, sources, safety notice, versions, and metadata. It never trusts those fields from generated output.

Decision examples are policy tests, not new API enum values:

| Situation | Required policy outcome |
|---|---|
| Current turn requests evidence destruction, evasion, fraud, or actionable wrongdoing | Refusal; high risk; deterministic safe alternative. |
| Current turn describes threat, injury, police/criminal exposure, or other serious legal risk without asking for wrongdoing | Professional/help escalation; no tactical unsafe advice. |
| Supported legal route but selected evidence is inadequate | Clarify or cautious no-source guidance; no fabricated source or strong legal claim. |
| Supported route with adequate approved evidence | Bounded guidance tied to selected evidence. |
| Non-legal or unsupported language/domain | Existing `unsupported` semantics. |

The implementation must not let a safety guard become the universal decision engine. The output-safety guard can reject/replace unsafe rendered text, but the finalizer re-applies the already authoritative policy outcome and never accepts draft-supplied classification.

## 6. Fingerprint and request identity

### 6.1 Contract blocker

The frozen v1 request currently has `session_id`, optional `chat_id`, `question`, `user_type`, and `language`; `request_id` exists only in the response and is generated inside `AgentRuntime`. Therefore a client retry after a timeout has no stable key with which the server can find the first attempt. Durable idempotency across HTTP attempts is impossible under the current input contract.

Before implementation, the contract owner must choose one transport. The recommended choice is a distinct opaque idempotency header (for example, an owner-approved `Idempotency-Key`) that the client repeats for the same logical operation. The store keeps only a versioned SHA-256 digest for lookup. The backend independently generates the public durable `request_id`, stores the mapping, and returns that same backend ID on replay.

A client-supplied body `request_id` remains a possible contract proposal only if owners explicitly approve an exception to the locked “backend owns IDs” boundary. It is not equivalent to adding a transport field: accepting it as the public ID would transfer identity authority to the client and requires an architecture/API decision.

The recommended semantics therefore use two identities: a client retry carrier and a backend-owned request ID. Legacy clients without a carrier may receive a backend request ID but have explicitly best-effort, non-retry-safe behavior if the owner keeps that compatibility path. This is **OWNER_DECISION_REQUIRED**, including header syntax/length, digest version, legacy behavior, OpenAPI/schema/frontend/evaluator changes, and error/status mapping. No code or error code is approved by this plan.

### 6.2 Canonical fingerprint proposal

After schema validation/default insertion but before semantic normalization, construct this canonical object in exactly this key set:

```json
{
  "chat_id": null,
  "contract_version": "v1",
  "language": "vi",
  "question": "<validation-canonical question>",
  "session_id": "<session>",
  "user_type": "unknown"
}
```

Rules:

1. Serialize JSON with lexicographically sorted keys, separators `(',', ':')`, UTF-8, and no ASCII escaping requirement (`ensure_ascii=False`). HTTP whitespace, property order, and equivalent JSON encoding do not affect the result.
2. Apply only contract-boundary trimming to `question` before fingerprinting because the frozen contract explicitly says to trim it. Preserve its internal whitespace, case, punctuation, diacritics, and Unicode code points. Do not use accent folding, topic normalization, tokenization, or semantic normalization. This makes contract-equivalent boundary whitespace the same request while ensuring substantively changed wording is a fingerprint mismatch.
3. Materialize defaults before fingerprinting: absent `chat_id` and explicit `null` are identical; absent `user_type` and explicit `"unknown"` are identical; absent `language` and explicit `"vi"` are identical. Unknown/extra properties are already rejected.
4. Include `session_id`, `chat_id`, `user_type`, `language`, and `contract_version`. Do not include the idempotency carrier or its digest, generated IDs, timestamps, context, policy output, or retrieval output. Different carriers over the same accepted payload therefore have the same request fingerprint but distinct carrier mappings.
5. Store the SHA-256 digest as exactly 64 lowercase hexadecimal characters, with no `sha256:` prefix, computed from the UTF-8 canonical JSON. SHA-256 is unkeyed; there is no application secret/salt. It is an equality/integrity value, not authentication. Do not log the canonical object or fingerprint alongside raw question text.
6. Version this algorithm as `fingerprint-v1` and persist the version. Tests use fixed Unicode/null/default vectors.

The exact stored request snapshot format is still **OWNER_DECISION_REQUIRED**. The proposed privacy-minimizing implementation stores user type/language/requested chat as typed columns and stores the question once in the user message; it does not duplicate raw legal text in an opaque request JSON blob. Recovery joins the request to its user message. If owners instead require a canonical JSON snapshot, retention/privacy policy must be approved first.

## 7. State machine and API behavior

The durable states are `RECEIVED`, `PROCESSING`, `COMPLETE`, `FAILED_RETRYABLE`, and `FAILED_FINAL`.

- A new valid request logically enters `RECEIVED`, inserts its one user message, and moves to `PROCESSING` inside Tx A. Because Tx A is atomic, another connection observes either no row or the committed `PROCESSING` row, never a committed request without its user message.
- A retryable pipeline failure moves `PROCESSING -> FAILED_RETRYABLE` in a short failure transaction.
- A final pipeline failure moves `PROCESSING -> FAILED_FINAL` and stores the exact final public error envelope.
- A same-fingerprint retry moves `FAILED_RETRYABLE -> PROCESSING`, increments `attempt_count`, and reuses the durable request/chat/user-message IDs; it never adds another user message. Because the proposed schema does not reserve an assistant ID before Tx B, a retry may generate a new unobserved assistant candidate ID.
- Tx B inserts one assistant message, stores the exact response, and moves `PROCESSING -> COMPLETE` atomically.

Symbols such as `REQUEST_IN_PROGRESS` and `IDEMPOTENCY_KEY_REUSED` below describe required semantics from ADR-007. They are proposed public codes until the contract owner approves their spelling, HTTP status, and envelope mapping.

| From | Event | Guard | To | Database effect | API result |
|---|---|---|---|---|---|
| no row | malformed/schema-invalid request | validation fails | no row | No chat, request, or message write. | Existing `invalid_request` behavior. |
| no row | valid request with supplied chat | chat absent/deleted/not owned by session | no row | No request or message write; ownership lookup reveals nothing. | Existing `chat_not_found` behavior. |
| no row | valid new logical request with approved carrier | no row for `(session_id, idempotency_key_digest)` | `RECEIVED -> PROCESSING` in Tx A | Atomically adopt service-generated backend request/chat/user candidates; resolve/create owned chat; insert carrier mapping/request and exactly one user whose ordering tuple becomes the context cutoff; set processing timestamps; commit. | Continue pipeline and return only the backend-owned request ID. |
| no row | valid legacy request without caller key | contract permits server-generated key | `RECEIVED -> PROCESSING` | Same as above, but transport retry is explicitly not guaranteed idempotent. | Continue; metadata may disclose best-effort mode only if contract owner approves. |
| `COMPLETE` | duplicate | same fingerprint | `COMPLETE` | Read only; no message/timestamp mutation. | Return byte-equivalent stored response envelope with original IDs. |
| `COMPLETE` | reused key | different fingerprint/version | `COMPLETE` | Read only. | Proposed `IDEMPOTENCY_KEY_REUSED`; mapping owner approval required. |
| `PROCESSING` | concurrent duplicate | same fingerprint and not stale | `PROCESSING` | Read only; no second execution/user message. | Proposed `REQUEST_IN_PROGRESS`; mapping/retry hint owner approval required. |
| `PROCESSING` | concurrent reused key | different fingerprint | `PROCESSING` | Read only. | Proposed `IDEMPOTENCY_KEY_REUSED`. |
| `FAILED_RETRYABLE` | retry | same fingerprint and retry policy allows | `PROCESSING` | Increment `attempt_count`; clear transient error/failure timestamp; retain request/chat/user-message IDs; update processing timestamp. No assistant ID exists yet. | Execute pipeline again. |
| `FAILED_RETRYABLE` | reused key | different fingerprint | `FAILED_RETRYABLE` | Read only. | Proposed `IDEMPOTENCY_KEY_REUSED`. |
| `FAILED_FINAL` | duplicate | same fingerprint | `FAILED_FINAL` | Read only. | Return exact stored final public error; do not execute. |
| `FAILED_FINAL` | reused key | different fingerprint | `FAILED_FINAL` | Read only. | Proposed `IDEMPOTENCY_KEY_REUSED`. |
| `PROCESSING` | deterministic successful finalization | response validates and IDs match request row | `COMPLETE` in Tx B | Insert exactly one assistant message; store exact response; set completion timestamp/status in same transaction. | Return completed response. |
| `PROCESSING` | retryable dependency failure | classified retryable | `FAILED_RETRYABLE` | Store safe error class/code/details, failure/update time; no assistant. | Existing approved dependency error if one exists; otherwise owner-approved mapping. |
| `PROCESSING` | deterministic client-caused failure discovered after begin | classified final/client | `FAILED_FINAL` | Store public final error envelope and failure fields; no assistant. | Return stored error. Such validation should normally occur before Tx A. |
| `PROCESSING` | internal invariant/contract failure | owner-approved classification says deterministic final | `FAILED_FINAL` | Store redacted internal classification and public error envelope; no assistant. | Existing `internal_error`; no stack or raw text. The durable mapping requires owner approval. |
| `PROCESSING` | output safety guard detects actionable unsafe draft | safe deterministic replacement is available | `PROCESSING` | No status change; record redacted guard result in memory/trace. | Finalize safe refusal/escalation, then normal Tx B. |
| `PROCESSING` | output/schema/evidence guard cannot create a valid safe response | owner-approved classification says deterministic final | `FAILED_FINAL` | Failure transaction; no assistant. | Stored public internal error. If the root cause is transient, the approved retryable row applies instead. |
| any durable row | validation/ownership request with same textual key but fails before idempotency | validation/ownership fails first | unchanged | Read/write ordering must not leak whether key exists. | Existing validation/ownership result. |
| Tx A open | process crash before commit | transaction incomplete | no row/no new message | SQLite rollback removes chat/request/user writes. | Client may retry as new. |
| `PROCESSING` committed | crash after user commit, before Tx B | row becomes stale under recovery policy | `FAILED_RETRYABLE` (after reconciliation) | Keep exactly one user; mark retryable in a recovery transaction; no assistant. | Before stale transition: in-progress; after transition: same-key retry runs. |
| Tx B open | crash after assistant insert but before commit | transaction incomplete | `PROCESSING` | SQLite rollback removes assistant and outcome/status updates together. | Recovery as stale processing; no duplicate assistant. |
| `COMPLETE` committed | crash before HTTP response reaches caller | same-fingerprint retry | `COMPLETE` | Read only. | Return stored response and original IDs. |
| `PROCESSING` | service restart while work may still be active in another worker | lease not expired | `PROCESSING` | No mutation. | In-progress semantics. |
| `PROCESSING` | restart/reconciler sees expired processing deadline | owner-approved stale policy | `FAILED_RETRYABLE` | Conditional update only if status/deadline still match; store recovery reason. | Subsequent same-key retry allowed. |

### Error classification

| Class | Examples | Durable state | Retry rule |
|---|---|---|---|
| client | schema, unsupported extra field, ownership failure | Usually no row; `FAILED_FINAL` only if discovered after Tx A | No retry under same key unless contract expressly says corrected payload must use a new key. |
| retryable dependency | unavailable snippet store/read failure, temporary SQLite busy after bounded retry, temporary trace sink only if configured as required | `FAILED_RETRYABLE` | Same fingerprint/key; increment `attempt_count`, reuse user. |
| deterministic-final candidate | impossible plan or repeatable schema/evidence invariant violation under unchanged artifacts | Proposed `FAILED_FINAL`; **OWNER_DECISION_REQUIRED** | Return a stored safe final error only after the exhaustive classification is approved. |
| unavailable stamped artifact | exact corpus/policy/retriever/generator version cannot be loaded | **OWNER_DECISION_REQUIRED** | Never silently use a different version; approve retry/final state and public mapping. |
| internal unknown | uncaught bug | **OWNER_DECISION_REQUIRED** | Never expose exception/raw data or repeat without a bounded approved policy. |

Stale `PROCESSING` timeout, lease/heartbeat behavior, maximum attempts, retry-after mapping, and whether request status is externally queryable are **OWNER_DECISION_REQUIRED**. A startup job must not blindly mark all `PROCESSING` rows retryable because another worker could still be handling them.

## 8. Minimal conversation context

Gate A loads no arbitrary history. `MinimalConversationContext` contains only:

- the current validated question (always present and authoritative);
- the most recent same-chat assistant clarification list, at most five items and at most 300 characters per item; and
- the most recent same-chat confirmed topic/domain from backend-authored structured assistant metadata, one topic identifier up to 64 characters.

The SQLite adapter assigns every Gate A user/assistant `messages.created_at` inside its serialized short write transaction. For an existing chat, it reads and parses at one fixed canonical UTC precision `chat_time_high_water = max(chats.created_at, chats.updated_at, MAX(messages.created_at))` inside the same `BEGIN IMMEDIATE`, then assigns `max(clock.now_utc(), chat_time_high_water + 1 microsecond)` and advances `chats.updated_at` to that value. For a new chat, one `clock.now_utc()` value initializes chat `created_at`/`updated_at` and the first user message consistently. The existing `(chat_id, created_at, message_id)` index then yields timestamps strictly increasing per chat even for empty existing chats and equal/backward clocks. The same invariant applies in Tx A/Tx B; timestamps precomputed outside the transaction are rejected. Any writer that bypasses this adapter is outside the Gate A reliability guarantee and is detected by store/architecture tests.

After current-turn safety, `load_bounded_context` uses the durable current user message's canonical chat-reload ordering tuple `(created_at, message_id)` as a content-agnostic cutoff. It selects the newest qualifying same-chat assistant clarification and confirmed topic strictly before that tuple; they may come from the same message or different messages. It revalidates session/chat ownership and returns only the bounded values plus provenance IDs.

The cutoff is fixed by Transaction A and reused on retry. An assistant from a distinct later request that completes early is not eligible merely because context loading occurs later. Content inspection and topic/clarification selection happen only in the `MINIMAL_CONTEXT` stage after safety; Transaction A does not inspect assistant content. The store never returns intervening rows or raw history to the pipeline, and it excludes prior user text, summaries, checklists, next steps, source prose, and other sessions/chats. A new chat has no assistant strictly before its current user cutoff and returns empty prior clarification/topic.

Precedence rules are deterministic:

1. Safety is evaluated on the current turn before context can influence routing. Unsafe current-turn intent overrides safe prior context.
2. A safe current turn after an unsafe prior turn is not made unsafe merely by history. Safety flags are not inherited.
3. Explicit current-turn topic/domain terms override the prior confirmed topic.
4. Prior topic may fill only an anaphoric/underspecified follow-up such as “Vậy cần giấy tờ gì?” and only when the current input does not explicitly switch topic.
5. Prior clarification can identify the expected missing fact but cannot supply a fact the user has not stated.
6. Retrieval uses the current normalized question plus the allowed topic identifier; it does not concatenate prose history.

Gate E, not Gate A, may propose broader summarized history after privacy, contradiction, recency, and evaluation controls exist.

## 9. Lexical retrieval and evidence boundary

The Gate A retrieval path is exactly:

> input normalization -> lexical candidate scoring -> deterministic metadata/topic boost -> dedupe by source ID -> configured adequacy threshold -> rank by score then source ID

The adapter reads the same 26 active snippets and exposes rank/score/reason without changing the source schema. No embedding or hybrid branch exists behind a disabled flag. Initial top-k/threshold values are frozen from the current implementation or explicitly benchmarked; they are not tuned against individual evaluation failures without a documented benchmark result.

Promotion to embeddings/hybrid retrieval is deferred. It requires a reviewed benchmark showing a material lexical recall gap using Recall@5, MRR, Precision@3, wrong-domain rate, no-source false-positive rate, and evidence-adequacy rate. Snippet count and “more sources returned” are not quality metrics.

Evidence selection converts lexical hits into an `EvidenceBundle`. Only selected, active, domain/topic-compatible corpus IDs can support plan points. The plan contract is:

```python
class GuidancePoint(BaseModel):
    point_id: str
    canonical_text: str
    supporting_source_ids: list[str]
    strength: Literal["informational", "cautious", "strong"]

class RenderedPoint(BaseModel):
    point_id: str
    text: str
```

An `AnswerPlan` contains ordered required and optional `GuidancePoint` entries grouped into the existing response slots (`summary`, `clarifying_questions`, `checklist`, `next_steps`). Stable point IDs are backend-owned registry values, not text hashes or generator-created values. High-risk language, refusals, escalation steps, and checklists are deterministic. In Gate A, rendering normally copies `canonical_text` exactly; this intentionally creates a firm structural baseline before a wording-only LLM is considered in Gate F.

The evidence guard enforces:

- every rendered `point_id` is in the plan's allowed set;
- there are no unknown or duplicate point IDs;
- all required point IDs are present;
- point ordering and slot placement match the plan;
- every point's source IDs are a subset of the selected evidence bundle;
- rendered output cannot add source IDs or authoritative fields;
- rendered strength cannot exceed planned strength; and
- final response sources are reconstructed from approved corpus objects, never copied from draft text.

These controls prove structural grounding and containment. They do not automatically prove legal correctness, source applicability, semantic entailment, completeness, or that a paraphrase preserved every legal nuance. Those remain corpus review, policy review, evaluation, and later human/NLI research concerns. Gate F may allow wording variation only under the same point-ID containment rules.

## 10. SQLite migration and transaction design

### 10.1 Proposed choice: additive table, not alteration of historical rows

Altering `messages` to carry request lifecycle columns would mix message and request invariants, require backfill for historical user/assistant pairs that cannot be reliably inferred, and make rollback risky. Gate A instead adds `analysis_requests`, referencing existing `chats` and `messages`. Existing `chats`, `messages`, and their two indexes remain unchanged. Historical rows are not backfilled; only analyze requests created after the migration receive lifecycle/idempotency guarantees. This limitation must be explicit in release notes and acceptance evidence.

### 10.2 Proposed exact migration

The following is the proposed migration contract for the recommended distinct-header design. It is not approved for execution until request-key transport, header validation/digest rules, stale policy, and stored-payload decisions are resolved. If owners instead approve a client-owned public `request_id`, this DDL must return to architecture review rather than being adapted silently.

The migrator owns the registry and executes this exact statement inside its migration transaction before loading any numbered resource; this statement is not part of `001_analysis_requests.sql`:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

It must exact-shape-check that registry even when it already exists. The proposed `001_analysis_requests.sql` resource body is:

```sql
CREATE TABLE IF NOT EXISTS analysis_requests (
    analysis_request_pk INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    idempotency_key_version TEXT NULL,
    idempotency_key_digest TEXT NULL CHECK (
        idempotency_key_digest IS NULL OR (
            length(idempotency_key_digest) = 64
            AND idempotency_key_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
    fingerprint_version TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL CHECK (
        length(request_fingerprint) = 64
        AND request_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    status TEXT NOT NULL CHECK (status IN (
        'RECEIVED', 'PROCESSING', 'COMPLETE',
        'FAILED_RETRYABLE', 'FAILED_FINAL'
    )),
    attempt_count INTEGER NOT NULL DEFAULT 1 CHECK (attempt_count >= 1),
    requested_chat_id TEXT NULL,
    chat_id TEXT NOT NULL,
    user_type TEXT NOT NULL,
    language TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NULL,
    response_payload TEXT NULL,
    error_class TEXT NULL CHECK (
        error_class IS NULL OR error_class IN ('client', 'retryable_dependency', 'final_deterministic', 'internal')
    ),
    last_error_code TEXT NULL,
    error_details_json TEXT NULL,
    contract_version TEXT NOT NULL,
    corpus_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    retriever_version TEXT NOT NULL,
    generator_mode TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    processing_started_at TEXT NOT NULL,
    processing_deadline_at TEXT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT NULL,
    failed_at TEXT NULL,
    UNIQUE (session_id, request_id),
    UNIQUE (user_message_id),
    CHECK ((idempotency_key_version IS NULL) = (idempotency_key_digest IS NULL)),
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id),
    FOREIGN KEY (user_message_id) REFERENCES messages(message_id)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (assistant_message_id) REFERENCES messages(message_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK ((status = 'COMPLETE') = (assistant_message_id IS NOT NULL)),
    CHECK ((status IN ('COMPLETE', 'FAILED_FINAL')) = (response_payload IS NOT NULL)),
    CHECK ((status = 'COMPLETE') = (completed_at IS NOT NULL)),
    CHECK ((status IN ('FAILED_RETRYABLE', 'FAILED_FINAL')) = (failed_at IS NOT NULL)),
    CHECK ((status IN ('FAILED_RETRYABLE', 'FAILED_FINAL')) = (error_class IS NOT NULL)),
    CHECK ((status IN ('FAILED_RETRYABLE', 'FAILED_FINAL')) = (last_error_code IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_analysis_requests_assistant_message
    ON analysis_requests(assistant_message_id)
    WHERE assistant_message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_analysis_requests_session_idempotency
    ON analysis_requests(session_id, idempotency_key_digest)
    WHERE idempotency_key_digest IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_analysis_requests_status_updated
    ON analysis_requests(status, updated_at);
CREATE INDEX IF NOT EXISTS ix_analysis_requests_chat_created
    ON analysis_requests(chat_id, created_at, analysis_request_pk);

```

Startup schema ownership and order are fixed. First, the preserved `SQLiteChatStore` base-schema bootstrap runs explicitly (not as a constructor side effect) with foreign keys enabled and one short `BEGIN IMMEDIATE`. Before writing, it accepts only (a) none of the four base objects or (b) the complete exact supported shape of `chats`, `messages`, `idx_chats_session_updated`, and `idx_messages_chat_created`. For (a), it creates and verifies all four inside that transaction; for (b), it verifies and commits without DDL. A partial or incompatible base shape fails before migration `001`, and any bootstrap additions roll back. Only after the base transaction commits does `migrator.py` apply `001_analysis_requests`. Thus every referenced table exists and has the reviewed shape before its foreign keys are declared; the plan does not rely on SQLite accepting references to missing tables.

The SQL block is the `001_analysis_requests` DDL resource body only; it deliberately contains no migration-registry DDL, `BEGIN`, `COMMIT`, `PRAGMA`, timestamp parameter, or migration-row insert. `migrator.py` owns the registry and the one migration transaction: enable foreign keys before the transaction, execute `BEGIN IMMEDIATE`, create or exact-shape-check `schema_migrations`, execute the DDL resource, verify the exact resulting request shape, insert `('001_analysis_requests', applied_at)`, and commit. Registry creation/acceptance, request DDL, request-shape acceptance, and migration-version recording therefore succeed or roll back together. Migration execution must verify the full existing table/index shape; `CREATE TABLE IF NOT EXISTS` alone is not sufficient to accept a partially incompatible schema. Reapplying an already-recorded migration is a no-op only after registry and request-shape verification. A mismatch rolls back/fails startup loudly and does not attempt an ad hoc repair.

The header itself is never stored: `idempotency_key_digest` is lowercase SHA-256 hex over the validated opaque UTF-8 carrier, versioned separately and excluded from the request fingerprint. The partial unique index permits multiple owner-approved legacy rows with no carrier while making one supplied carrier map to one backend request per session. The status checks deliberately make `assistant_message_id` non-null only for `COMPLETE`; Tx B sets it with the inserted assistant. `FAILED_FINAL.response_payload` stores the exact public final error envelope. `COMPLETE.response_payload` stores the exact success envelope. `FAILED_RETRYABLE` has no final payload. All JSON is validated before storage and on load. `prompt_version` is exactly `"none"` and `generator_mode` is exactly `"deterministic"` in Gate A; a separate `generator_version` identifies the deterministic renderer.

### 10.3 Tx A: begin/check and exactly one user

Use an explicit `BEGIN IMMEDIATE` with a bounded SQLite busy timeout:

1. Revalidate supplied-chat ownership inside the transaction. For a missing chat, create the owned chat in this same transaction only after idempotency determines the request is new.
2. For a supplied approved carrier, select `(session_id, idempotency_key_digest)` and apply the duplicate table in section 7 before creating any message. A legacy no-carrier request has no cross-attempt lookup guarantee.
3. For a new request, atomically adopt the backend request/chat/user-message candidate IDs and deterministic new-chat title supplied by `BeginRequest`, assign the user `created_at` inside Tx A with the strict per-chat monotonic rule in section 8, insert the carrier mapping and `analysis_requests` row as `RECEIVED`, insert the required `chats.title` for a new chat, insert exactly one `messages(role='user', content_type='text')`, update the request to `PROCESSING`, and update the chat timestamp. Leave `assistant_message_id` null. If the carrier already exists, ignore every candidate/title and return stored identity.
4. For `FAILED_RETRYABLE` same-fingerprint retry, update status/`attempt_count`/timestamps only; retain the original user-message ordering cutoff and never insert another user message.
5. Commit and run the pipeline outside a database transaction.

SQLite's write lock serializes same-carrier contenders through partial `UNIQUE(session_id, idempotency_key_digest)` while `UNIQUE(session_id, request_id)` independently protects backend request identity. The second transaction sees the first committed status; uniqueness is the final guard even if application checks race. `ChatStore.begin_request` converts only recognized carrier-uniqueness races into duplicate semantics; it does not catch every `IntegrityError` as idempotency.

### 10.4 Tx B: assistant, response, complete

Immediately before `ResponseFinalizer` and outside any database transaction, the orchestrator obtains an attempt-local assistant candidate ID from `IdGenerator`, records it in the request-local state, and gives it to the finalizer. The finalized response and candidate then enter `complete_request` together. This preserves backend ID authority without holding Tx B open during finalization.

Use a second explicit short transaction:

1. Select the request by `(session_id, request_id)` and require `PROCESSING`, matching fingerprint and expected `attempt_count`.
2. Validate the already-finalized response request/chat/user IDs against durable values, validate that its assistant ID equals the candidate carried by `CompleteRequest`, and revalidate the API schema. Tx B does not generate IDs or run finalization.
3. Assign the assistant `created_at` inside Tx B using the same strict per-chat monotonic rule, then insert exactly one structured assistant message using the candidate ID. It becomes durable only if this transaction commits.
4. Store canonical `response_payload`, set `assistant_message_id`, `status='COMPLETE'`, `completed_at`, and `updated_at`.
5. Commit, then return the already stored outcome.

Assistant insert and `COMPLETE` are inseparable. A crash before commit rolls both back. A crash after commit is recovered by replaying the stored response. No transaction remains open during safety, routing, retrieval, planning, rendering, or guards.

### 10.5 Failure and recovery transactions

After Tx A, every exception is classified. `ChatStore.fail_request` conditionally updates only the matching `PROCESSING` row and `attempt_count`. It records `last_error_code`, redacted diagnostic fields, timestamps, and either `FAILED_RETRYABLE` or `FAILED_FINAL`; for final failure it also stores the validated public error envelope in `response_payload`. The attempt count was already incremented when that attempt atomically entered `PROCESSING`, so failure records it but does not increment it a second time. If the failure transaction itself cannot commit, the request remains `PROCESSING` and the stale-recovery mechanism handles it.

Startup/restart reconciliation must use a compare-and-set update on an expired `processing_deadline_at`; it cannot reset non-expired rows. The deadline duration, heartbeat policy, and multi-worker ownership model require owner approval. Recovery reuses the durable request/chat/user-message IDs and stamped artifacts. There is no durable assistant ID before successful Tx B; an uncommitted candidate may be replaced on retry without creating a duplicate. Recovery does not infer or append a new user message.

### 10.6 Existing DB, tests, and rollback

- Current ignored developer DB: back it up, apply the additive migration in place, verify schema and existing chat counts, and never instruct developers to delete it. No old message is linked retroactively.
- Tests: every persistence/idempotency/concurrency test receives a fresh `tmp_path` database and runs the migrator twice to prove idempotency. No test reads `data/vietlaw_chat.sqlite3`.
- Rollback of application code: point composition back to the old runtime while leaving the additive table/indexes in place; existing chat/message behavior is compatible.
- Rollback of schema: only after backup and downtime, remove migration row `001_analysis_requests` and drop `analysis_requests`; SQLite drops its two automatic unique-constraint indexes and the four named indexes (`ux_analysis_requests_assistant_message`, `ux_analysis_requests_session_idempotency`, `ix_analysis_requests_status_updated`, and `ix_analysis_requests_chat_created`) with the table. This loses Gate A request/outcome history and is not the default. Prefer a forward fix.
- Backfill: none. Any later backfill is a separately reviewed migration because old user/assistant pairing and request IDs are not authoritative.

SQLite gives exactly-once message effects for one database file when all writers obey these transactions. It does not provide distributed exactly-once semantics across replicated databases or external side effects. Gate A has no external generation/tool side effect, which keeps that limitation bounded.

## 11. File-level implementation map

Every row below is future implementation work. “New” means the path does not exist today.

| Exact target path | Existing responsibility | Concrete planned change | Dependencies / migration impact | Exact test path and cases | Primary risk | Rollback |
|---|---|---|---|---|---|---|
| `backend_lite/app/main.py` | FastAPI bootstrap; delegates concrete wiring to `dependencies.py`; CORS currently allows only `Content-Type` and `Accept`. | Become the sole production composition root: construct `SystemClock`, `PrefixedUuidIdGenerator`, SQLite/lexical/generator/trace adapters, pure stages, and `AnalyzeService`; explicitly run exact base-schema bootstrap, then migration `001`, then register readiness/routes; register an injected-ID error-handler factory. Only if OD-01 approves the distinct idempotency header, add that exact header to CORS `allow_headers`; otherwise preserve current CORS. No policy branch. | Depends on all ports/adapters; invokes ordered base bootstrap/additive migration at startup; conditional public transport/CORS change is blocked on OD-01. | `backend_lite/tests/test_health.py::test_health_all_ready`; `backend_lite/tests/integration/test_composition_root.py::{test_analyze_service_is_wired,test_clock_and_id_generator_shared_with_store_and_handlers,test_base_bootstrap_precedes_001,test_primary_backend_not_imported}`; `backend_lite/tests/contract/test_analyze_idempotency_contract.py::test_cors_preflight_allows_approved_key_header`. | Import cycle, hidden global primitives, startup against partial schema, or browser preflight rejecting an approved header. | Wire old `AgentRuntime` back; keep additive table; do not widen CORS without OD-01. |
| `backend_lite/app/dependencies.py` | Current concrete service locator and runtime builder. | Reduce to typed container/accessor or remove after imports migrate; no independent composition authority. | Route/main transition only; no DB shape. | `backend_lite/tests/integration/test_composition_root.py::test_single_composition_root`. | Two divergent wiring paths. | Restore current builder while service remains isolated. |
| `backend_lite/app/application/__init__.py` (new) | None. | Package marker exporting no concrete adapter. | None. | `backend_lite/tests/unit/test_application_ports.py::test_application_package_imports_without_adapters`. | Accidental adapter re-export. | Remove export/package after route rollback. |
| `backend_lite/app/application/ports.py` (new) | Effect protocols currently live in `runtime/protocols.py` and use `Any`. | Add typed `ChatStore(begin_request/complete_request/fail_request/load_bounded_context)`, `Retriever.retrieve`, `AnswerGenerator.generate`, `TraceSink.record_transition`, `Clock`, `IdGenerator`, and typed command/result DTO references. | Depends only on `contracts/internal.py`; no SQLite/FastAPI import. | `backend_lite/tests/unit/test_application_ports.py::{test_ports_have_typed_use_case_methods,test_ports_import_without_sqlite_or_fastapi,test_fake_ports_drive_service,test_clock_and_id_generator_are_injected}`. | Leaky concrete types or over-broad CRUD port. | Keep old protocols until new service switch. |
| `backend_lite/app/application/analyze_service.py` (new) | Use case is embedded in `AgentRuntime.analyze`. | Orchestrate exact bounded order; receive `InputNormalizer`, `LiteLanguageDetector`, and `ChatTitleService` as pure constructor collaborators; create ID/title candidates before `begin_request`; apply typed `NormalizedInput` during `ACTIVATE_STATE`; honor stored duplicate/retry IDs; create assistant candidate before finalization/outside Tx B; classify failures; call finalizer then `complete_request`. | Contract-owner carrier; effect ports, pure collaborators, internal stages, store migration. | `backend_lite/tests/unit/test_analyze_service.py::{test_constructor_receives_effect_ports_and_admission_helpers,test_begin_receives_backend_id_candidates,test_begin_receives_deterministic_new_chat_title,test_duplicate_discards_candidates_and_uses_stored_identity,test_activation_applies_normalized_input_and_language_before_safety,test_raw_input_unchanged,test_exact_stage_order,test_complete_duplicate_short_circuits,test_processing_duplicate_short_circuits,test_retry_reuses_user,test_assistant_candidate_created_before_finalizer_outside_store_tx,test_failure_calls_fail_request_once,test_no_state_wholesale_persist}`; `backend_lite/tests/integration/test_gate_a_vertical_slice.py`. | Partial effect after user persistence; stage authority leakage; normalization after safety; finalization inside DB transaction; duplicate candidate overwriting stored IDs/title. | Switch route to old runtime. |
| `backend_lite/app/application/fingerprint.py` (new) | No current stable logical-request fingerprint or carrier-digest helper; `AgentRuntime` generates an ID per invocation. | Implement `fingerprint-v1` over accepted payload and a separately named `idempotency-key-digest-v1` over the validated opaque carrier. Both store exactly 64 lowercase SHA-256 hex; neither logs raw input, and the request fingerprint excludes the carrier/digest. | Approved key transport/header validation and existing request schema. | `backend_lite/tests/unit/test_request_fingerprint.py::{test_fixed_unicode_vector,test_property_order_irrelevant,test_absent_defaults_equal_explicit_defaults,test_boundary_trim_equal,test_internal_text_change_mismatch,test_identity_field_changes_mismatch,test_storage_is_64_lowercase_hex,test_carrier_digest_fixed_vector,test_raw_carrier_not_stored,test_carrier_excluded_from_request_fingerprint}`. | Conflating carrier identity with payload fingerprint or changing normalization silently. | Keep both algorithms independently versioned; old rows retain their versions. |
| `backend_lite/app/services/input_normalizer.py`, `backend_lite/app/services/language_detector.py` | Current pure normalization/accent folding and frozen Vietnamese/unsupported detection used inside `AgentRuntime`; no focused direct tests exist. | Preserve algorithms as injected pure activation helpers; wrap their tuple/string outputs into strict `NormalizedInput`; no state mutation, I/O, safety, route, or decision authority. | Accepted `RawInput`, internal typed result; composed in `main.py`. No migration. | `backend_lite/tests/unit/pipeline/test_normalization.py::{test_raw_input_preserved,test_vietnamese_forms_exact,test_ascii_vietnamese_detected,test_frozen_unsupported_language,test_normalization_runs_before_safety,test_no_policy_fields_produced}`. | Relevance/language drift or hidden stage reorder. | Keep current helper algorithms and old runtime wiring. |
| `backend_lite/app/services/chat_title.py` | Deterministically compacts question or maps an optional known topic; current runtime calls it before routing with question only. | Keep `ChatTitleService.make(question)` as injected pure admission helper; `AnalyzeService` supplies `new_chat_title` in `BeginRequest`; store only adopts it for a winning new-chat row and never derives business title. | Accepted question; no route dependency or migration. | `backend_lite/tests/unit/test_chat_title.py::{test_current_question_title_parity,test_whitespace_and_72_char_limit,test_no_topic_result_required}`; `backend_lite/tests/integration/test_gate_a_vertical_slice.py::test_new_chat_title_and_reload_parity`. | NOT NULL chat insert failure or title drift caused by routing timing. | Reuse existing helper unchanged through rollback. |
| `backend_lite/app/contracts/__init__.py` (new) | None. | Package boundary for internal types; do not re-export API response as mutable internal state. | Pydantic only. | `backend_lite/tests/unit/test_internal_contracts.py::test_contract_package_has_no_adapter_imports`. | Confusing internal and external contracts. | Remove after service rollback. |
| `backend_lite/app/contracts/state.py` (new) | Current dataclass `runtime/agent_state.py`. | Add the exact `AnalysisState` fields in section 4, nested typed values, and direct top-level `trace: list[StageTrace] = Field(default_factory=list)`. Validate no unknown state fields. | Depends on internal contracts, existing API enums where approved. Never persisted whole. | `backend_lite/tests/unit/test_analysis_state.py::{test_all_required_fields,test_trace_default_is_not_shared,test_state_rejects_unknown_fields,test_state_is_not_store_payload}`. | Mutable defaults or state becoming a god-object. | Keep existing dataclass runtime isolated. |
| `backend_lite/app/contracts/internal.py` (new) | DTOs are spread across dataclasses/Pydantic models and `Any`. | Define begin outcomes, status enum, fingerprint/version DTOs, minimal context, safety/route/retrieval/evidence/decision, `GuidancePoint`, `RenderedPoint`, `AnswerPlan`, guard results, failure types, and `StageTrace`. | Must not create public API values. Error-code mapping stays outside until approved. | `backend_lite/tests/unit/test_internal_contracts.py::{test_status_enum,test_guidance_point_strength,test_begin_result_union,test_version_stamps_gate_a_defaults,test_internal_models_forbid_extra}`. | Internal type accidentally treated as normative public contract. | Leave unused while old runtime serves. |
| `backend_lite/app/pipeline/safety.py` (new) | Logic in `unsafe_detector.py` plus some authority in `safety_guard.py`. | Pure current-turn `SafetyPolicy`; distinguish harmful intent, legal high risk, and safe/insufficient-evidence; emit policy IDs/reasons, not final normal decision. Gate A preserves frozen/current policy behavior rather than narrowing unsafe-token intent. | Existing `data/unsafe_patterns.json`, normalizer, policy version. | `backend_lite/tests/unit/pipeline/test_safety.py::{test_harmful_intent_is_distinct,test_high_risk_is_not_harmful,test_frozen_policy_parity_is_explicit,test_current_unsafe_overrides_context,test_safe_current_not_tainted_by_history,test_lawful_unsafe_token_case_is_gate_b_inventory}` plus current `backend_lite/tests/test_safety.py`. The last case records/defer-labels the Gate B limitation; it is not a Gate A green assertion. | False positive/negative or inherited-history unsafe state. | Keep current detector behind old runtime. |
| `backend_lite/app/pipeline/context.py` (new) | `SameChatContextBuilder` loads up to eight message bodies. | Validate and apply only `MinimalConversationContext`; explicit-topic/current-turn precedence; no DB access and no full text history. | `ChatStore.load_bounded_context`. | `backend_lite/tests/unit/pipeline/test_context.py::{test_only_allowed_fields,test_explicit_topic_wins,test_generic_followup_uses_last_confirmed_topic,test_prior_clarification_does_not_invent_fact,test_unsafe_flags_not_inherited}`. | Context bleed or stale-topic override. | Configure service to use current-turn only. |
| `backend_lite/app/pipeline/routing.py` (new) | Domain/topic routing is in `domain_classifier.py` and consumes full-history-derived terms. | Implement deterministic typed `RoutingPolicy`: current input first, allowed prior topic only for underspecified follow-up, candidate scores/reasons, and no risk/decision mutation. | Normalized input, safety result, minimal context. | `backend_lite/tests/unit/pipeline/test_routing.py::{test_current_explicit_topic_wins,test_generic_followup_uses_allowed_topic,test_topic_shift_drops_old_topic,test_route_does_not_set_decision,test_safety_result_cannot_be_downgraded}`. | Stale route context or hidden decision authority. | Use current classifier through the old runtime. |
| `backend_lite/app/pipeline/retrieval.py` (new) | Retrieval orchestration embedded in concrete `KeywordRagRetriever`. | Build typed retrieval query from normalized current turn + allowed topic, invoke port, preserve ranked result/reasons/version, and map unavailable corpus to retryable classification. | `Retriever` port; no corpus implementation import. | `backend_lite/tests/unit/pipeline/test_retrieval.py::{test_query_excludes_history_prose,test_rank_and_version_preserved,test_unavailable_is_retryable}`. | Query accidentally contains raw history. | Route retrieval through old service during parity window. |
| `backend_lite/app/pipeline/evidence.py` (new) | Source selection/citation logic is split across retriever, generator, citation guard, response builder. | Select adequate active hits into `EvidenceBundle`; map sources to plan point allowlists; produce explicit no-source result; never label identity verification as legal correctness. | Corpus records from retrieval; thresholds/config version. | `backend_lite/tests/unit/pipeline/test_evidence.py::{test_only_retrieved_active_ids_selected,test_no_source_is_explicit,test_wrong_domain_rejected,test_source_identity_not_legal_correctness,test_point_support_subset}`. | Treating source presence/count as evidence adequacy. | Fall back to cautious/no-source path. |
| `backend_lite/app/pipeline/decision.py` (new) | `decision_policy.py`, `risk_classifier.py`, and response confidence logic. | Implement `ResponseDecisionPolicy` and `ConfidenceCalculator` after safety/route/evidence; one typed authoritative decision object; guard changes can only maintain/lower confidence. | Safety, routing, evidence DTOs; existing public enum only. | `backend_lite/tests/unit/pipeline/test_decision.py::{test_harmful_refuses,test_legal_high_risk_escalates,test_insufficient_evidence_cautions_not_refuses,test_adequate_evidence_guides,test_guard_never_increases_confidence}`. | Safety universalizes refusal or sources automatically imply confidence. | Revert route to old decision services. |
| `backend_lite/app/pipeline/generation.py` (new) | `LiteContentGenerator` mixes decision, content, source IDs, and rendering. | Deterministically build ordered `AnswerPlan` with stable point IDs, canonical text, source support, strength, and slots; high-risk/checklist plans are templates. Invoke renderer only after plan. | Decision/evidence; point registry; `AnswerGenerator` port. Gate A prompt `none`. | `backend_lite/tests/unit/pipeline/test_generation.py::{test_plan_is_deterministic,test_high_risk_plan_is_template,test_checklist_has_stable_ids,test_draft_contains_only_rendered_points,test_same_input_same_plan}`. | Unstable IDs or prose regains decision authority. | Use current deterministic generator through old runtime. |
| `backend_lite/app/pipeline/finalize.py` (new) | `response_builder.py` plus guard-final fields. | `ResponseFinalizer` reconstructs approved sources, applies authoritative IDs/domain/risk/decision/confidence/safety notice/metadata/version stamps, validates `AnalyzeResponse`, and exposes no raw trace. | All guard results; existing API schema. | `backend_lite/tests/unit/pipeline/test_finalize.py::{test_backend_fields_ignore_draft,test_sources_rebuilt_from_bundle,test_safety_notice_exact,test_metadata_versions_exact,test_trace_is_redacted,test_response_schema_valid}`. | Draft-controlled metadata/source/classification. | Old response builder while old runtime active. |
| `backend_lite/app/guards/evidence_guard.py` (new) | `citation_guard.py` validates only used source IDs and a small set of strong markers. | Enforce allowed/required/unique/order/slot/strength/source containment for point IDs; return typed failures/replacements; make no entailment/legal-correctness claim. | Answer plan, draft, evidence bundle. | `backend_lite/tests/unit/guards/test_evidence_guard.py::{test_unknown_id_rejected,test_duplicate_id_rejected,test_missing_required_rejected,test_order_rejected,test_source_subset_enforced,test_strength_elevation_rejected,test_valid_plan_passes}`. | False assurance from structural checks. | Deterministic finalizer can render canonical plan directly. |
| `backend_lite/app/guards/output_safety_guard.py` (new) | `safety_guard.py` scans clauses and can overwrite classification. | Scan every rendered point with clause-boundary-aware policy; refusal in an earlier clause cannot license later unsafe advice; replace with pre-approved safe points or fail closed; never trust/emit new authority fields. | Safety policy/version; deterministic safe plan registry. | `backend_lite/tests/unit/guards/test_output_safety_guard.py::{test_refusal_before_unsafe_clause_fails,test_same_clause_negation_passes,test_evidence_destruction_fails,test_safe_preservation_passes,test_safe_replacement_is_deterministic}` plus current safety regression tests. | Clause-boundary false negative/positive. | Render the authoritative safe plan directly for guarded cases. |
| `backend_lite/app/guards/schema_guard.py` (new) | Final response is currently re-validated inline by `AgentRuntime`. | Validate draft structure before evidence/output guards and validate the finalized external response after finalization; reject unknown fields/types and classify invariant failures. It does not repair arbitrary malformed output. | Internal Pydantic contracts and approved API schemas. | `backend_lite/tests/unit/guards/test_schema_guard.py::{test_malformed_draft_fails_loud,test_unknown_draft_field_fails,test_invalid_final_response_fails,test_valid_internal_and_external_shapes_pass}`. | Silent coercion hides generator or contract defects. | Gate A renderer can be called directly and existing final response validation retained during rollback. |
| `backend_lite/app/adapters/sqlite_store.py` (new) | Existing SQLite store has separate chat/message transactions and no request lifecycle. | Implement `ChatStore.begin_request`, `complete_request`, `fail_request`, and `load_bounded_context`; carrier-digest lookup mapped to backend `request_id`; content-agnostic context cutoff from the durable current-user ordering tuple; exact Tx A/Tx B/failure/recovery; duplicate matrix; JSON validation; and compare-and-set `attempt_count`. It may delegate legacy chat CRUD during transition. | Proposed additive DDL; carrier/header/context-cutoff owner decisions. | `backend_lite/tests/integration/test_sqlite_migration.py`; `backend_lite/tests/integration/test_idempotency.py`; `backend_lite/tests/integration/test_idempotency_concurrency.py`; `backend_lite/tests/integration/test_crash_recovery.py`; `backend_lite/tests/integration/test_minimal_context_store.py`; current `backend_lite/tests/test_chat_store.py`. | Locking, partial writes, incompatible developer DB, conflated carrier/public ID authority, or later-request context contamination. | Route analyze to old store/runtime; leave additive schema. |
| `backend_lite/app/stores/sqlite_chat_store.py` | `SQLiteChatStore.initialize()` currently creates the base schema as a constructor side effect with `IF NOT EXISTS`. | Preserve legacy CRUD but replace implicit initialization with an explicit base-schema bootstrap owned by this adapter: accept only an absent or exact complete base object set, create all four base objects atomically only when absent, verify exact columns/checks/FKs/indexes, and fail before `001` on a partial/incompatible base. It never creates `schema_migrations` or `analysis_requests`. | Must commit successfully before `migrator.py`; no base-schema version/backfill. | `backend_lite/tests/integration/test_sqlite_migration.py::{test_empty_db_bootstraps_exact_base_before_001,test_exact_legacy_base_is_accepted_unchanged,test_partial_legacy_base_fails_before_001_and_rolls_back,test_base_constructor_has_no_schema_side_effect}` plus current `backend_lite/tests/test_chat_store.py`. | Constructor mutation, accepting malformed legacy DDL, or two owners for request schema. | Route rollback may call the explicit base bootstrap and retain legacy CRUD; it must not restore ambiguous Gate A startup ordering. |
| `backend_lite/app/adapters/migrator.py` (new) | No versioned request-schema migration exists; base schema is currently initialized independently. | After the exact base bootstrap has committed, own `schema_migrations` and one migration `BEGIN IMMEDIATE`: enable FKs beforehand, create or exact-shape-check the registry inside the transaction, execute the request-only DDL resource, verify exact request shape, insert the version row, commit; any failure rolls registry/request DDL and version together. Refuse to run if the exact base objects are absent/incompatible; stop startup without deleting/rebuilding a DB. | Migration resources and SQLite adapter startup; never bootstraps `chats`/`messages`. | `backend_lite/tests/integration/test_sqlite_migration.py::{test_empty_db_migrates_after_base_bootstrap,test_existing_chat_db_migrates,test_001_rejects_missing_base,test_second_run_noop,test_partial_registry_shape_fails_loud,test_partial_request_shape_fails_loud,test_failed_migration_rolls_back,test_no_nested_transaction,test_version_row_atomic_with_ddl}`. | Nested transactions, FK targets absent at apply time, or recording a version for partial DDL. | Route rollback leaves the additive table and uses the already-verified base schema. |
| `backend_lite/app/adapters/migrations/001_analysis_requests.sql` (new) | No migration resource exists; request schema is absent. | Store only the reviewed section-10 `analysis_requests` table/index DDL—no registry DDL, transaction control, PRAGMA, timestamps, or migration-row insert. The migrator owns `schema_migrations`, supplies the atomic boundary, and records the version after shape verification. | Owner-approved final request DDL. No `analysis_requests` backfill. | `backend_lite/tests/integration/test_sqlite_migration.py::{test_001_has_exact_request_shape_and_preserves_existing_rows,test_001_does_not_define_migration_registry,test_001_contains_no_transaction_control}`. | SQL/document drift, a second registry owner, or nested transaction control. | Leave unapplied; after apply, prefer forward fix over destructive down migration. |
| `backend_lite/app/adapters/lexical_retriever.py` (new) | Existing `KeywordRagRetriever` loads JSON and scores in one class. | Implement typed `Retriever`; normalization/lexical score/metadata boost/dedupe/threshold/stable ordering; expose reasons/version; use exactly current 26 active snippets. | `JsonSnippetStore` initially; no vector dependency. | `backend_lite/tests/unit/adapters/test_lexical_retriever.py::{test_26_snippet_fixture,test_deterministic_rank,test_metadata_boost_after_lexical,test_dedupe,test_threshold_no_source,test_wrong_domain_filtered}` and existing `backend_lite/tests/test_rag.py`. | Accidental relevance change during refactor. | Adapter wrapper delegates current scorer until parity snapshot passes. |
| `backend_lite/app/adapters/deterministic_answer_generator.py` (new) | Current deterministic generator is topic-specific but not plan-bound. | Implement `AnswerGenerator.generate`; render each planned point in order, normally `text == canonical_text`; emit no IDs except point IDs and no source/classification metadata. Set mode/version. | `AnswerGenerator`, plan DTO. | `backend_lite/tests/unit/adapters/test_deterministic_answer_generator.py::{test_generate_canonical_text_copy,test_order_preserved,test_no_authoritative_fields,test_generator_mode_and_version}`. | Renderer expands authority. | Finalizer directly uses canonical plan text. |
| `backend_lite/app/adapters/runtime_primitives.py` (new) | `AgentRuntime`, error handlers, and SQLite store import `uuid4`/`utc_now` directly. | Implement `SystemClock.now_utc/monotonic` and `PrefixedUuidIdGenerator.new_id`; return timezone-aware UTC and approved `req_`/`chat_`/`msg_user_`/`msg_asst_` prefixes. The SQLite adapter receives `Clock` for in-transaction monotonic-per-chat timestamps; no global time/UUID calls remain in the Gate A path. | `Clock`, `IdGenerator`, internal `IdKind`; composed only in `main.py`. No DB migration. | `backend_lite/tests/unit/adapters/test_runtime_primitives.py::{test_now_is_utc_aware,test_monotonic_non_decreasing,test_id_prefix_by_kind,test_ids_are_unique,test_unknown_kind_rejected}`; timestamp ordering in `backend_lite/tests/integration/test_minimal_context_store.py`. | Backward/equal clocks, wrong ID prefix, or globals bypass deterministic tests. | Inject fixed clock/deterministic IDs in tests; route rollback retains old helpers. |
| `backend_lite/app/observability/trace.py` (new) | Runtime stores phase names, errors, elapsed time in mutable state/response metadata. | Add redacting `TraceSink.record_transition` adapter and stage context helper; record typed timing/status/count/ID summaries only. Trace failures are non-fatal unless explicitly configured. | `Clock` injection; trace port. No full state persistence. | `backend_lite/tests/unit/observability/test_trace.py::{test_fields_and_duration,test_no_question_or_draft_text,test_error_redacted,test_sink_failure_does_not_change_response}`. | Sensitive legal text leakage. | Use no-op trace sink. |
| `backend_lite/app/config.py` | Paths, RAG top-k, full-history context limit, and general service settings. | Add only reviewed version/threshold/busy-timeout/stale-policy settings; remove the analyze path's use of `context_message_limit`; validate Gate A prompt/mode invariants at startup. | Stale-policy owner decision and corpus/retriever versioning. | `backend_lite/tests/unit/test_gate_a_config.py::{test_prompt_none_and_deterministic_mode,test_invalid_timeout_rejected,test_context_history_limit_not_used_by_gate_a}`. | Environment drift changes deterministic behavior. | Keep old settings consumed only by old runtime. |
| `backend_lite/app/schemas/api.py` | Public frozen v1 models; request lacks a retry carrier and response ID is backend-generated. | Only after owner approval: preserve backend-owned `request_id`, map the chosen distinct header/carrier transport, keep response fields/enums compatible, forbid extras, and regenerate machine artifacts. A body `request_id` needs an explicit ID-authority exception. | `docs/api_contract.md`, OpenAPI, schemas, frontend/evaluator. | `backend_lite/tests/contract/test_analyze_idempotency_contract.py::{test_key_transport,test_backend_owns_request_id,test_legacy_behavior_if_allowed,test_duplicate_envelopes,test_error_mapping}` plus current `backend_lite/tests/test_analyze_contract.py`. | Unapproved contract drift or client-controlled public IDs. | Do not change until owner decision; Gate A idempotency remains blocked. |
| `backend_lite/app/api/routes_analyze.py` | Calls `AgentRuntime`. | Extract the approved idempotency carrier without treating it as a public ID, call `AnalyzeService`, and map only approved outcomes; no state/policy/persistence/ID-generation code. | Contract decision and service. | `backend_lite/tests/contract/test_analyze_idempotency_contract.py`; `backend_lite/tests/integration/test_gate_a_vertical_slice.py`. | Route invents HTTP code, logs raw carrier, or transfers ID authority to the client. | Switch dependency back to old runtime. |
| `frontend/src/App.tsx`, `frontend/src/api/client.ts` | `App.tsx` owns one UI submit flow; `client.ts` posts `/api/analyze` with JSON and no retry carrier. | Keep the shared frontend carrier-disabled by default. Conditional on OD-01 and dual-target rollout approval: create one opaque carrier for each logical submit in `App.tsx`, pass it explicitly to `client.ts`, send the approved header, and retain that same carrier only for a transport retry of that logical submit. Enable it only after every configured backend/proxy passes independent header/replay/CORS checks, or behind an approved fallback-only target capability that cannot send it to production. A new submit gets a new carrier; cancellation, server response, or abandonment ends its lifetime. Never put it in the body or reuse it across changed payloads. | OD-01, dual-backend public-contract compatibility, browser crypto/key generation, target capability/config, each target's CORS allowlist, and API-client retry ownership; no database migration and no `backend/` implementation in this plan. | Proposed `frontend/src/api/client.test.ts::{carrier_disabled_without_target_capability,new_logical_submit_gets_new_carrier,transport_retry_reuses_carrier,changed_payload_never_reuses_carrier,approved_header_exact,capability_is_target_scoped,legacy_no_carrier_compatibility}`; Backend Lite `test_cors_preflight_allows_approved_key_header`; owner-supplied black-box header/replay/preflight evidence for every enabled API target before shared rollout. | Browser preflight failure, accidental key reuse, a fallback capability leaking to production, or treating a user resubmit as a transport retry. | Leave shared frontend unchanged until both rollout preconditions and OD-01 are approved; fallback server support may remain unused by the browser. |
| `backend_lite/app/errors.py`, `backend_lite/app/api/error_handlers.py` | Approved current errors/envelope; handler imports `uuid4` and creates a new error request ID. | Expose a handler factory registered by `main.py` with injected `IdGenerator`; pre-admission errors receive a backend-owned prefixed correlation/request ID, while admitted duplicate/final errors replay the durable logical `request_id`. Map only approved outcomes; no direct UUID import or replacement ID for a known request. | `IdGenerator`; owner-approved public codes/statuses. | `backend_lite/tests/contract/test_analyze_idempotency_contract.py::{test_pre_admission_error_id_is_backend_owned,test_final_error_replays_same_request_id,test_processing_mapping,test_reused_key_mapping,test_unknown_error_is_redacted,test_handler_has_no_uuid_import}`. | New unapproved public code, client/global-generated ID, or unstable error replay. | Retain current handlers until approved route/service switch. |
| `contracts/openapi.json` (new, repository root) | Absent. | Generate and check in the approved API contract after docs owner accepts semantics. | Normative docs and FastAPI model. | New `backend_lite/tests/contract/test_machine_contract_drift.py::test_openapi_matches_checked_in`. | Generated artifact mistaken for approved semantics. | Regenerate from last approved contract. |
| `contracts/generated/*.schema.json` (new, repository root) | Absent. | Generate request/response/error schemas for both independent backends and evaluator. | Approved OpenAPI. | `backend_lite/tests/contract/test_machine_contract_drift.py::{test_request_schema,test_response_schema,test_error_schema}`. | Dual-backend drift. | Restore last approved generated files. |

### 11.1 Explicit migration-impact register

The implementation table combines dependencies and migration notes for readability. This register makes the database impact of every planned path explicit; “none” means no table, column, index, or backfill change.

| Exact target path | Migration impact |
|---|---|
| `backend_lite/app/main.py` | No schema definition; invokes exact base bootstrap and then the reviewed idempotent request migrator at startup. |
| `backend_lite/app/dependencies.py` | None. |
| `backend_lite/app/application/__init__.py` | None. |
| `backend_lite/app/application/ports.py` | None; typed abstractions only. |
| `backend_lite/app/application/analyze_service.py` | None directly; consumes the new request lifecycle through `ChatStore`. |
| `backend_lite/app/application/fingerprint.py` | None directly; produces values for the new table's `fingerprint_version` and `request_fingerprint` columns. |
| `backend_lite/app/services/input_normalizer.py`, `backend_lite/app/services/language_detector.py` | None; reused as pure activation helpers. |
| `backend_lite/app/services/chat_title.py` | None; reused as a pure new-chat admission helper. |
| `backend_lite/app/contracts/__init__.py` | None. |
| `backend_lite/app/contracts/state.py` | None; `AnalysisState` is never persisted whole. |
| `backend_lite/app/contracts/internal.py` | None. |
| `backend_lite/app/pipeline/safety.py` | None. |
| `backend_lite/app/pipeline/context.py` | None. |
| `backend_lite/app/pipeline/routing.py` | None. |
| `backend_lite/app/pipeline/retrieval.py` | None. |
| `backend_lite/app/pipeline/evidence.py` | None. |
| `backend_lite/app/pipeline/decision.py` | None. |
| `backend_lite/app/pipeline/generation.py` | None. |
| `backend_lite/app/pipeline/finalize.py` | None directly; produces validated payload consumed by Tx B. |
| `backend_lite/app/guards/evidence_guard.py` | None. |
| `backend_lite/app/guards/output_safety_guard.py` | None. |
| `backend_lite/app/guards/schema_guard.py` | None. |
| `backend_lite/app/adapters/sqlite_store.py` | Uses the additive `analysis_requests` table, two unique constraints, four named indexes (including carrier and assistant partial uniqueness), and existing `chats`/`messages`; the current user row supplies the immutable context cutoff; no old-row backfill. |
| `backend_lite/app/stores/sqlite_chat_store.py` | Owns exact bootstrap/verification of the existing `chats`/`messages` tables and two existing indexes before migration `001`; adds no request table and backfills nothing. |
| `backend_lite/app/adapters/migrator.py` | Adds/verifies `schema_migrations` and applies `001_analysis_requests` atomically and idempotently. |
| `backend_lite/app/adapters/migrations/001_analysis_requests.sql` | Adds only `analysis_requests`, two unique constraints, two partial unique indexes (carrier and assistant), and two lookup indexes; it does not define `schema_migrations`, alters no existing table, and backfills nothing. |
| `backend_lite/app/adapters/lexical_retriever.py` | None. |
| `backend_lite/app/adapters/deterministic_answer_generator.py` | None. |
| `backend_lite/app/adapters/runtime_primitives.py` | None; provides injected time/ID effects only. |
| `backend_lite/app/observability/trace.py` | None; trace is in memory/structured logs, not a new database record. |
| `backend_lite/app/config.py` | None. |
| `backend_lite/app/schemas/api.py` | None directly; approved request-key semantics determine how the new request record is addressed. |
| `backend_lite/app/api/routes_analyze.py` | None. |
| `frontend/src/App.tsx`, `frontend/src/api/client.ts` | None directly; remains carrier-disabled unless every selected target is compatible or an approved fallback-only target capability gates the owner-approved opaque carrier; never stores it in SQLite. |
| `backend_lite/app/errors.py`, `backend_lite/app/api/error_handlers.py` | None directly; approved final error envelope is stored in `response_payload`. |
| `contracts/openapi.json` | None; machine contract artifact. |
| `contracts/generated/*.schema.json` | None; generated machine contract artifacts. |

No `backend/**` business implementation is imported or modified by this plan. Both backends may consume the normative docs, generated contract artifacts, corpus format, and evaluation cases; they do not share pipeline/store/policy code.

## 12. Observability and durable version stamps

Each `StageTrace` has exactly:

- `stage`;
- `started_at` and `finished_at` in UTC;
- `duration_ms` from a monotonic clock;
- `status` (`started`, `completed`, or `failed`); downstream stages that never start have no fabricated entry, and pre-state duplicate replay uses a separate bounded correlation event;
- `input_summary_redacted` and `output_summary_redacted`, containing only enums, counts, source/point IDs, booleans, ranks, and versions; and
- optional `error_code`, containing only a redacted approved operational code (no exception message, stack, raw question, generated text, source snippet, or chat history).

The trace sink may log/measure these events, but the full trace and full `AnalysisState` are not durable request payloads. Response metadata may include a bounded list of stage names/statuses only if already allowed by the API contract; it must not leak raw summaries.

`VersionStamps` are captured before execution and stored on `analysis_requests`:

| Stamp | Gate A value rule |
|---|---|
| contract | approved contract identifier, initially `v1` |
| corpus | deterministic digest/release of the exact 26-record corpus |
| policy | reviewed safety/routing/decision policy release/digest |
| prompt | exactly `none` |
| retriever | e.g. approved lexical implementation version; value finalized in code review |
| generator | mode exactly `deterministic` plus deterministic renderer version |

The values are also emitted as redacted trace fields and response metadata only where the existing metadata contract permits. They are never inferred from a model response.

## 13. Exact test matrix

All new SQLite tests use fresh `tmp_path` databases. Concurrency tests use separate connections and a barrier; mocks alone are insufficient.

| Category | Exact target test file | Required cases/assertions |
|---|---|---|
| Ports | `backend_lite/tests/unit/test_application_ports.py` | Application imports without SQLite/FastAPI; fakes satisfy typed methods; no `Any` use-case payload; store exposes `begin_request`/`complete_request`/`fail_request`/`load_bounded_context`; generator exposes `generate`; trace sink exposes `record_transition`; service receives ports through its constructor. |
| Dependency direction | `backend_lite/tests/unit/test_dependency_direction.py` | `test_pure_layers_import_no_fastapi_sqlite_provider_sdk_or_concrete_adapter`; `test_only_main_composes_concrete_adapters`; `test_backend_lite_imports_no_backend_business_module`; `test_backend_imports_no_backend_lite_business_module`. Scan `application/**`, `pipeline/**`, `contracts/**`, and `guards/**`, plus both backend import directions; machine-shape tests are not a substitute. |
| Runtime primitives | `backend_lite/tests/unit/adapters/test_runtime_primitives.py` | UTC-aware wall clock, monotonic source, exact ID prefixes/uniqueness, unknown kind rejection; no direct global time/UUID imports in the explicitly mapped new Gate A analyze modules, without falsely scanning unchanged legacy CRUD. |
| Activation/title | `backend_lite/tests/unit/pipeline/test_normalization.py`, `backend_lite/tests/unit/test_chat_title.py`, `backend_lite/tests/unit/test_analyze_service.py` | Raw input remains immutable; typed normalization/language is applied within `ACTIVATE_STATE` before safety; helpers produce no policy fields; accepted-question title is passed through `BeginRequest`; a duplicate discards its title candidate; new-chat reload preserves title parity. |
| State | `backend_lite/tests/unit/test_analysis_state.py` | All required top-level fields; direct `AnalysisState.trace` list independent per instance; unknown fields fail; final response initially null; state cannot be passed to store DTO validation. |
| Internal contracts | `backend_lite/tests/unit/test_internal_contracts.py` | Status set; begin result variants; stable point/strength validation; Gate A prompt/mode values; `test_valid_transition_sequence`; invalid transition/result rejected. |
| Fingerprint/carrier | `backend_lite/tests/unit/test_request_fingerprint.py` | Fixed SHA-256 request and carrier vectors; JSON key order irrelevant; absent/default and absent/null rules; boundary whitespace equivalence; internal whitespace/case/diacritic/question changes mismatch; session/chat/user/language/contract changes mismatch; carrier excluded from request fingerprint; raw carrier not retained/logged; no semantic normalizer call. |
| Migration | `backend_lite/tests/integration/test_sqlite_migration.py` | On an empty DB, base bootstrap commits the exact `chats`/`messages` tables and two indexes before `001`; an exact legacy base is unchanged; a missing/partial/incompatible base fails before request migration and rolls back additions. Then migrate empty/current legacy fixtures; run twice; verify exact registry and request columns/checks/indexes/FKs; prove `001` contains neither registry nor transaction control and the migrator has no nested transaction; prove registry creation/acceptance, request DDL, exact-shape acceptance, and version-row recording commit or roll back atomically; preserve old counts/content; no backfill; ignored default DB untouched. |
| Idempotency | `backend_lite/tests/integration/test_idempotency.py` | New carrier -> backend request ID + one user; same carrier COMPLETE -> same stored response/backend IDs and unchanged counts; same carrier PROCESSING -> in-progress; FAILED_RETRYABLE -> increment `attempt_count`/no new user; FAILED_FINAL -> same stored error; same carrier with each fingerprint mismatch -> reuse-key outcome; distinct carriers over same payload create distinct backend requests; legacy no-carrier behavior is explicitly best effort if approved. |
| Concurrency | `backend_lite/tests/integration/test_idempotency_concurrency.py` | Two connections with same session/carrier digest/fingerprint but different candidate IDs result in one stored candidate set, one request/user, and one execution winner; loser receives stored IDs; same carrier/different fingerprint writes nothing extra; distinct-carrier same-chat requests cannot see an assistant ordered at/after their durable current-user cutoff; concurrent complete produces one assistant; SQLite busy is bounded/classified. |
| Crash recovery | `backend_lite/tests/integration/test_crash_recovery.py` | Crash before Tx A commit leaves nothing; after Tx A leaves processing+one user and null assistant ID; Tx B crash rolls assistant/status/outcome back together; an uncommitted candidate ID may change on retry; crash after complete replays the committed assistant ID; stale compare-and-set does not steal live row; recovered retry reuses request/chat/user IDs. |
| Ownership | `backend_lite/tests/integration/test_analysis_ownership.py` | Missing/deleted/other-session chat gives same result and no request/message; duplicate lookup cannot bypass ownership; bounded context cannot cross session/chat; new chat remains owned/no orphan. |
| Minimal context | `backend_lite/tests/integration/test_minimal_context_store.py` and `backend_lite/tests/unit/pipeline/test_context.py` | New chat returns null context; Tx A/Tx B allocate strict per-chat timestamps inside serialized transactions under equal/backward fake clocks; an existing empty chat advances beyond chat created/updated high-water; current user `(created_at, message_id)` is the content-agnostic cutoff; clarification/topic may come from distinct newest qualifying assistants before it; only bounded fields/IDs returned; retry/newer-turn/interleaving cannot contaminate; selection after safety; limits/no prior user/source prose; explicit topic wins; generic follow-up uses topic; safety not inherited. |
| Safety | `backend_lite/tests/unit/pipeline/test_safety.py`, `backend_lite/tests/unit/guards/test_output_safety_guard.py`, existing `backend_lite/tests/test_safety.py` | Harmful vs high-risk vs insufficient evidence; current-turn isolation/priority; frozen policy parity and exact Gate B limitation inventory. Separately, output-guard safe preservation language passes and unsafe advice after an earlier refusal clause fails. Gate A does not require deferred lawful-token policy cases to turn green. |
| Routing | `backend_lite/tests/unit/pipeline/test_routing.py` | Current explicit route wins; bounded topic resolves only underspecified follow-up; topic shift clears old route; route emits candidates/reasons and cannot set final decision or weaken safety. |
| Retrieval | `backend_lite/tests/unit/adapters/test_lexical_retriever.py`, existing `backend_lite/tests/test_rag.py` | Exactly 26 active snippets; stable tie order; normalization/lexical/boost/dedupe/threshold sequence; wrong domain/no match; unavailable corpus retryable; current relevance cases unchanged. |
| Evidence/plan | `backend_lite/tests/unit/pipeline/test_evidence.py`, `backend_lite/tests/unit/pipeline/test_generation.py`, `backend_lite/tests/unit/guards/test_evidence_guard.py` | Active selected IDs only; explicit no-source; stable point IDs/order; required/unknown/duplicate/strength/source subset; deterministic high-risk/checklist; identity validation not labelled legal correctness. |
| Schema guard | `backend_lite/tests/unit/guards/test_schema_guard.py` | Malformed/unknown internal draft fails loudly before evidence guard; invalid finalized response fails before Tx B; valid strict internal/external structures pass without silent repair. |
| Decision/finalization | `backend_lite/tests/unit/pipeline/test_decision.py`, `backend_lite/tests/unit/pipeline/test_finalize.py` | Refuse/escalate/cautious/guidance matrix; confidence cannot increase after guard; draft cannot set authority; sources rebuilt from evidence; safety notice/IDs/schema/version exact. |
| Vertical slice | `backend_lite/tests/integration/test_gate_a_vertical_slice.py` | Exact stage order; no long transaction during pipeline; one safe legal demo; one unsafe refusal; one high-risk escalation; one same-topic follow-up; one healthy no-source response; source identity; exact safety notice; one user/assistant; live/reload equivalence; deterministic fallback/repeat; no LLM/embedding import/call; trace redaction; failure transitions. |
| Public contract | Existing `backend_lite/tests/test_analyze_contract.py`, `backend_lite/tests/test_chat_endpoints.py`, `backend_lite/tests/test_frontend_integration_contract.py`, `backend_lite/tests/test_session_boundary.py`; new `backend_lite/tests/contract/test_analyze_idempotency_contract.py` | Existing v1 response/reload/session behavior preserved; chosen request-key semantics and only owner-approved codes/statuses; stored final outcome replays exact request ID. |
| Dual-backend contract | `backend_lite/tests/contract/test_machine_contract_drift.py` | Checked-in OpenAPI/generated schemas match approved API models; backend_lite emits valid response; the bidirectional business-import prohibition is enforced by the dependency-direction scan above, not inferred from schema parity. This CI gate is proposed, not enabled in Gate A without owner approval. |
| Evaluation | Existing `evaluation/tests/test_mvp_suite.py`, `evaluation/tests/test_runner.py`, `evaluation/tests/test_oracles.py`, and remaining `evaluation/tests/**`; evaluation CLI profiles | Evaluator self-tests pass; legacy and smoke results recorded; MVP selector runs exactly its reviewed 68 executions under seed `20260713`; report exact failures/blockers; optional full is diagnostic/report-only; no forced green. |

The vertical test injects a recording store, retriever, generator, and trace sink to prove stage ordering and authority, then repeats with real temporary SQLite/JSON adapters. A fake alone cannot prove transaction behavior; the real-adapter test cannot alone prove every failure injection.

## 14. Implementation phases and checkpoints

### Phase 0 — owner decisions and contract baseline

1. Approve request-id/idempotency-key transport and whether legacy no-key requests remain accepted.
2. Approve processing/reuse public error codes, HTTP statuses, response envelope, retry hint, and request-status exposure.
3. Approve stale-processing duration/worker ownership/max attempts and request snapshot retention.
4. Record current OpenAPI from FastAPI and establish the normative docs-to-machine-artifact review flow; do not auto-declare generated artifacts normative.
5. Freeze the current 26-snippet corpus digest and lexical parity fixtures.

**Checkpoint:** no implementation starts on idempotency-facing API behavior until these owner decisions are documented.

### Phase 1 — contracts and dependency inversion

1. Add typed internal contracts and safe trace defaults.
2. Add the six minimum effect ports, including separately injected `Clock` and `IdGenerator`.
3. Implement fingerprint fixed vectors.
4. Add pure safety/context/decision/evidence/plan/finalize unit tests first.

**Checkpoint:** application/pipeline packages import without FastAPI, SQLite, or primary-backend business code.

### Phase 2 — additive persistence

1. Add a real migration runner with schema-shape verification.
2. Implement Tx A, duplicate outcomes, Tx B, failure transitions, and bounded context.
3. Prove temp-DB migration, concurrency, and crash boundaries.
4. Apply only to a backed-up ignored developer DB as a manual rehearsal; never delete it.

**Checkpoint:** every table-driven transition has a database assertion; one logical request cannot create more than one user/assistant message.

### Phase 3 — deterministic pipeline/adapters

1. Port current safety/routing behavior into typed pure stages while correcting authority boundaries.
2. Port lexical behavior with stable parity and explicit threshold/evidence selection.
3. Build deterministic plans and renderer, evidence guard, output-safety guard, confidence, and finalizer.
4. Add redacted trace/version stamps.

**Checkpoint:** 26-snippet parity is measured; no LLM/vector dependency/import/config path exists; structural containment tests pass.

### Phase 4 — vertical integration and compatibility

1. Wire `AnalyzeService` in the composition root, initially under a test-only selection or short-lived rollback switch.
2. Run current backend_lite contract, chat, session, follow-up, safety, RAG, language, frontend-reload, and health tests.
3. Regenerate/verify machine contract artifacts only after owner approval.
4. Switch the route default, verify response reload equality, then keep old runtime unreachable for one rollback window.

**Checkpoint:** legacy frontend behavior remains valid; a completed duplicate returns stored IDs/outcome; every failure after Tx A has a durable status.

### Phase 5 — evaluation and evidence

1. Run evaluator self-tests and schema/fault validation.
2. Run legacy, smoke, and MVP profiles against a temporary-DB backend_lite instance.
3. Confirm MVP selection is exactly 68 executions: 44 curated plus 24 generated, every generated case `reviewed` and `gate_eligible`, no quarantined variant, and no duplicate normalized question. The approved seed is `20260713`; a different seed must be rejected. This is evaluator validation, not corpus expansion.
4. Record exact pass, fail, blocker, no-source, wrong-domain, and safety results. Do not tune individual cases or make backend_lite “pass” by weakening thresholds.
5. Stop the service and verify the port is free.

**Checkpoint:** Gate A may be accepted with known target-backend blockers if implementation invariants pass and the evaluation report is honest; product/MVP readiness remains a separate decision.

## 15. Acceptance checklists

### Planning acceptance (this document)

- [x] Maps current paths and identifies that requested application/contracts/pipeline/adapters packages are absent.
- [x] Defines dependency direction and minimum effect ports.
- [x] Defines all required `AnalysisState` fields and safe trace default.
- [x] Defines request fingerprint semantics, null/default rules, hash, and current request-id gap.
- [x] Provides a transition matrix including duplicate, mismatch, retry, ownership, failures, concurrency, crash, and restart.
- [x] Compares additive `analysis_requests` with altering current tables and provides proposed exact DDL/indexes/nullability/checks/backfill/rollback.
- [x] Defines Tx A, Tx B, failure transaction, and exactly-once boundaries without a long transaction.
- [x] Defines minimal context and current-turn/safety priority.
- [x] Defines the evidence-plan structural boundary without claiming legal correctness.
- [x] Gives a file-level change/test/risk/rollback row for every required target path.
- [x] Gives categorized exact test files/cases and implementation phases.
- [x] Keeps Gate A deterministic over 26 snippets with no LLM/embedding/hybrid scope.

### Later implementation acceptance

- [ ] All owner decisions in section 16 are resolved in normative artifacts.
- [ ] `git diff` contains only reviewed implementation scope; no primary-backend business sharing or corpus expansion.
- [ ] All new internal contracts forbid unknown fields and mutable defaults are isolated.
- [ ] Application layer imports no FastAPI/SQLite/concrete adapter.
- [ ] Migration runs twice, validates exact shape, preserves old chats/messages, and never requires DB deletion.
- [ ] Every state transition and crash boundary is proven with real temporary SQLite connections.
- [ ] New/duplicate/retry/concurrent requests create at most one user and one assistant message per logical request.
- [ ] Tx B proves assistant insert, stored response, and `COMPLETE` are atomic.
- [ ] Minimal context returns no full history and cannot contaminate current-turn safety.
- [ ] Final classification, confidence, sources, IDs, notice, and metadata are backend-authored.
- [ ] Evidence guard enforces point/source/order/strength containment and documentation avoids legal-correctness claims.
- [ ] Output-safety clause-boundary regressions pass.
- [ ] Trace/log/response inspection finds no raw question, generated prose, source snippet, or history in trace data.
- [ ] Durable versions show prompt `none` and generator mode `deterministic`.
- [ ] Existing backend_lite contract/session/reload/frontend tests remain green.
- [ ] Evaluator self-tests pass; legacy/smoke/MVP results and exact blockers are recorded without threshold weakening.
- [ ] Server exits cleanly and temporary runtime port/database are cleaned without touching the ignored developer DB.

## 16. Decisions, risks, and owners

| Topic | Status | Current plan / question | Required owner |
|---|---|---|---|
| Gate A bounded deterministic architecture | **DECIDED** | State-first single-pass pipeline; no autonomous loop/TOMTIT. | Architecture |
| No LLM/embedding/hybrid/corpus expansion | **DECIDED** | 26 active snippets, lexical retrieval, deterministic renderer. | Architecture/evaluation |
| Independent backend implementations | **DECIDED** | Share normative API semantics, machine contract artifacts, corpus format, evaluation; no shared business package. | Architecture |
| Request identity input gap | **OWNER_DECISION_REQUIRED** | Prefer a distinct idempotency header mapped by versioned digest to a backend-generated `request_id`; approve validation and legacy no-carrier semantics. A body client-owned public ID needs an explicit authority exception. The shared frontend stays carrier-disabled until all enabled targets pass independent header/replay/CORS checks or an approved fallback-only capability isolates the header. | API/product/frontend/evaluation/backend owners |
| Request status exposure | **OWNER_DECISION_REQUIRED** | Decide whether processing is only an analyze response or queryable endpoint; no endpoint is proposed as approved. | API/product |
| Public error/status mapping | **OWNER_DECISION_REQUIRED** | Approve spelling/status/envelope for in-progress and reused-key semantics; do not invent codes in implementation. | API owner |
| Historical row migration | **OWNER_DECISION_REQUIRED** | Recommend additive table with no backfill; owner must accept that guarantees apply only to new Gate A requests. | Data/architecture |
| Stored request payload format/retention | **OWNER_DECISION_REQUIRED** | Prefer typed columns + one question copy in user message; approve privacy/retention or canonical JSON snapshot. | Data/privacy/product |
| Stale `PROCESSING` restart | **OWNER_DECISION_REQUIRED** | Approve deadline, heartbeat/worker ownership, max attempts, artifact retention, and compare-and-set recovery. | Reliability/operations |
| SQLite exactly-once boundary | **DECIDED** | Exactly once for messages/outcome in one SQLite file with compliant writers; no distributed/external-side-effect claim. | Reliability |
| Assistant plus complete transaction | **DECIDED** | One Tx B; never separate assistant and status commits. | Reliability |
| Stable point-ID registry | **OWNER_DECISION_REQUIRED** | Approve code-owned versioned IDs, required-point catalogue, and rename policy; never text hashes/generator IDs. | Legal content/architecture |
| Response mapping for deterministic plan slots | **OWNER_DECISION_REQUIRED** | Approve which plan points are required in summary/clarification/checklist/next-steps without changing public schema. | API/legal content |
| Exact migration DDL and request-message linkage | **OWNER_DECISION_REQUIRED** | Approve Section 10's surrogate key, deferred message FKs, uniqueness, nullable fields, and indexes after key/payload/stale choices. | Data/reliability |
| Version retention on retry | **OWNER_DECISION_REQUIRED** | Approve artifact-retention duration and the safe public outcome when an exact stamped version is unavailable. | Reliability/policy/API |
| Exhaustive failure classification | **OWNER_DECISION_REQUIRED** | Map each storage, corpus, invariant, and internal failure to retryable/final durability and an existing or approved safe envelope. | Reliability/API |
| Machine-artifact generation ownership and Gate A scope | **OWNER_DECISION_REQUIRED** | Approve generation/review flow and whether artifact creation/drift enforcement belongs to Gate A before creating or gating on `contracts/openapi.json` and generated schemas. | API/CI owners |
| Trace sink durability/retention/access | **OWNER_DECISION_REQUIRED** | Choose structured logs only versus a durable operational sink; approve retention, redaction review, and access control. Full state/trace is not persisted by default. | Operations/privacy/security |
| Public stage/version metadata | **OWNER_DECISION_REQUIRED** | Approve the bounded stage/version fields, if any, exposed in existing `metadata`; do not inherit current `runtime_trace` accidentally. | API/privacy/operations |
| Last confirmed topic derivation | **OWNER_DECISION_REQUIRED** | Approve strict current-user ordering cutoff, newest qualifying same-chat assistant selection after safety, recognized-topic registry, retry reuse, and null behavior. | Product/conversation/architecture |
| Police-tactical decision mapping | **OWNER_DECISION_REQUIRED** | Select deterministic refusal versus escalation semantics where frozen documents permit ambiguity, or approve an explicit reason-coded branch. | Safety/legal/product |
| Confidence calibration/explanation | **OWNER_DECISION_REQUIRED** | Approve deterministic inputs, thresholds, downgrade rules, and metadata wording without implying legal certainty. | Product/evaluation/legal |
| Refusal/escalation source display | **OWNER_DECISION_REQUIRED** | Decide whether safety-policy evidence is shown or sources remain empty; never present internal safety policy as law. | Safety/legal/product |
| Safety reason-code taxonomy | **OWNER_DECISION_REQUIRED** | Approve stable codes distinguishing harmful intent from a victim/high-risk report. | Safety/legal/architecture |
| Legacy runtime/state naming during migration | **PROPOSED** | Retain compatibility aliases for one rollback window, then remove duplicate authority in a separate reviewed cleanup. | Architecture/maintainers |
| Stage-name enum persistence | **PROPOSED** | Keep one versioned internal stage enum and record redacted transitions; exact public/durable exposure follows the metadata/trace decisions above. | Architecture/operations |
| Lawful text containing unsafe tokens | **DEFERRED** | Gate B owns any change; Gate A preserves frozen safety semantics, and intent-level narrowing requires separate policy correction/regression evidence. | Safety/legal/evaluation |
| Unsupported-language/bilingual ordering | **DEFERRED** | Preserve frozen Vietnamese-only Gate A behavior; bilingual safety is separate work. | Product/safety |
| Full state checkpoint/resume | **DEFERRED** | Recovery creates a fresh state; do not persist/resume the whole runtime object. | Reliability/architecture |
| Gate F wording equivalence and point provenance | **DEFERRED** | Wording-equivalence/strength review, LLM provider choice, semantic NLI, and public point provenance require later explicit approvals. | Safety/legal/API |
| Retrieval-promotion governance | **OWNER_DECISION_REQUIRED** | Resolve before later promotion: assign benchmark reviewers, numeric thresholds, and the later gate/blocking status only after lexical baseline evidence. It is not a Gate A coding blocker. | Retrieval/evaluation/product/legal |
| Distributed/external-effect idempotency | **DEFERRED** | Gate A guarantees only one SQLite-file durable effects; future providers/tools require their own keys and recovery contracts. | Reliability/operations |
| Production-backend refactor | **DEFERRED** | Teammate-owned `backend/` remains independent and unchanged by fallback Gate A. | Production backend owner |
| Drift CI | **PROPOSED** | Compare approved OpenAPI/generated schemas and both backend responses; do not make a known-red mandatory job. | CI/API owners |
| Broader conversation memory | **DEFERRED** | Gate E after privacy/contradiction/recency evaluation. | Architecture/product |
| Wording-only LLM | **DEFERRED** | Gate F only under point-ID/source/strength/order containment; high-risk/checklist remain deterministic. | Safety/legal/architecture |
| Embedding/hybrid retrieval | **DEFERRED** | Promote only after reviewed lexical benchmark shows a recall gap. | Retrieval/evaluation |

Primary risks and mitigations:

1. **False idempotency confidence:** without a caller-stable key, HTTP retry safety is impossible. Block the claim and expose the owner decision.
2. **SQLite contention:** keep Tx A/Tx B/failure operations short, use `BEGIN IMMEDIATE`, bounded busy timeout, and real two-connection tests.
3. **Crash leaves a user-only turn:** it is an intentional recoverable `PROCESSING` record, not an orphan; retry reuses it and Tx B adds at most one assistant.
4. **Stale worker double-completes:** `attempt_count`/status compare-and-set plus assistant/message uniqueness; stale policy must not steal a live lease.
5. **Context contamination:** query only the last assistant clarification/topic and make current-turn safety/topic authoritative.
6. **Evidence theater:** point/source containment is structural, not proof of legal correctness; measure wrong-domain/no-source/evidence adequacy.
7. **Contract drift:** normative docs require human approval; generated OpenAPI/schemas enforce shape only after approval.
8. **Refactor relevance regression:** snapshot current lexical ranks and run existing RAG/evaluation cases before tuning.
9. **Sensitive trace leakage:** typed summaries and negative tests; no full state/raw text persistence in trace.
10. **Rollback data loss:** application rollback leaves additive schema; destructive schema rollback is last resort after backup.

## 17. Evaluation and rollout evidence

The implementation report must include, without treating this plan as test evidence:

1. HEAD and dirty-scope snapshot before implementation.
2. Migration shape and twice-run output on a temp database plus an existing-schema fixture.
3. Unit/integration/contract test commands with counts and failures.
4. Concurrency and each crash-injection result, including message/request counts.
5. Corpus count/digest and confirmation that no corpus record changed.
6. Trace redaction sample containing only allowed fields.
7. Legacy, smoke, and MVP evaluation commands/results, exact blocker IDs, and selector review/quarantine counts.
8. No-LLM/no-embedding proof by dependency/config/import inspection and injected-call assertions.
9. Frontend optimistic response versus reload equality.
10. Service shutdown and free-port verification.

The reproducible runtime sequence uses a temporary `CHAT_DB_PATH`, starts backend_lite on `127.0.0.1:8010`, then runs the repository's approved CLI syntax for legacy, smoke, and:

```bash
python3 -m evaluation.cli run \
  --base-url http://127.0.0.1:8010 \
  --suite mvp \
  --seed 20260713
```

The independently observed pre-Gate-A backend_lite baseline (legacy 31/31, smoke 19/19, MVP 59/68 with eight blocker cases) is a comparison target, not a hard-coded assertion and not proof of the new implementation. Any changed result must name the exact case IDs and causal stage. The evaluator's 68/44/24 selection invariants remain exact even when backend results change.

Do not report a passing evaluator implementation as a passing target backend. Separate evaluator/platform correctness from the backend_lite target result and from MVP product readiness.

## 18. Rollback strategy

Rollback is layered:

1. **Before route switch:** new packages are unreachable; remove their composition wiring only. Existing runtime continues unchanged.
2. **After route switch, before schema use is widespread:** switch the composition root back to `AgentRuntime`; retain `analysis_requests` for diagnosis.
3. **Policy/retrieval regression:** revert the new adapter/stage version and keep old stamped rows immutable; completed outcomes continue replaying from storage.
4. **Migration problem:** stop writes, back up DB, inspect `schema_migrations` and exact shape. Prefer forward migration. Drop the additive table only when loss of Gate A request history is explicitly accepted.
5. **Contract rollback:** restore the last owner-approved docs/OpenAPI/generated schemas/frontend behavior together; never roll back one artifact alone.

Completed stored outcomes are historical facts. A code rollback must not regenerate or silently rewrite them.

## 19. Definition of Gate A readiness

Gate A is ready for full implementation only when the request-key transport, public duplicate/error mapping, stale-processing policy, historical-row/no-backfill policy, payload retention, stable point-ID/section mapping, exact DDL/linkage, version-retention behavior, exhaustive failure classification, machine-artifact ownership/scope, trace retention and public metadata, last-topic derivation, police-tactical mapping, confidence calibration, refusal-source display, and safety reason-code taxonomy are approved. It is implementation-complete only when the later checklist in section 15 is satisfied and exact evaluation failures are reported.

This plan is detailed enough to implement without redesigning the core dependency direction, state authority, transaction boundaries, context limits, retrieval mode, evidence-plan containment, or test strategy. It intentionally does **not** pre-approve new public contract codes or claim production-scale distributed exactly-once semantics.

Direct answers:

- **Is dependency inversion explicit?** Yes: `AnalyzeService` depends on typed ports; only the composition root selects SQLite/lexical/trace/generator adapters.
- **Can concurrent duplicates create two user messages?** Not if Tx A and the unique `(session_id, request_id)`/user-message constraints are implemented as specified; real two-connection tests are mandatory.
- **What happens after a crash immediately after the user commit?** The durable row remains `PROCESSING` with exactly one user and no assistant ID. An owner-approved stale reconciliation moves it to `FAILED_RETRYABLE`; retry reuses the request/chat/user IDs, may create a fresh unobserved assistant candidate at finalization, and does not append another user.
- **Does evidence containment prove legal correctness?** No. It proves structural plan/source containment only.
- **Are embeddings or an LLM part of Gate A?** No. Prompt version is `none`; generator mode is `deterministic`; retrieval is lexical over the existing 26 snippets.
- **Can implementation begin with no owner decisions?** Pure internal contracts and test scaffolding can be prepared, but externally correct idempotency, recovery timing, error mapping, payload retention, and machine-contract updates require the approvals listed above.
