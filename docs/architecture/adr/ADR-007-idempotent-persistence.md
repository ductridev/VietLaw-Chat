# ADR-007: Idempotent Persistence

- **Status:** PROPOSED — planning-only; contract decisions called out below require owner approval before implementation
- **Scope:** Gate A request identity, SQLite persistence, retries, concurrency, and crash recovery
- **Depends on:** `docs/api_contract.md`, ADR-001, ADR-002, ADR-006
- **Supersedes:** the current best-effort behavior in which separate user/assistant writes can leave an untracked partial turn

## Decision markers

- **DECIDED:** locked by the approved architecture prompt or frozen MVP specifications.
- **PROPOSED:** implementation direction that preserves the locked behavior but still needs normal review.
- **OWNER_DECISION_REQUIRED:** a product/API/storage choice must be approved before code depending on it is written.
- **DEFERRED:** intentionally outside Gate A.

These markers are especially important here. The frozen v1 API does not currently accept an idempotency key and does not define public errors for duplicate in-flight or key-reuse outcomes. This ADR names required observable outcomes but does not pretend that unapproved API codes or HTTP statuses already exist.

## Context and problem

The current `backend_lite` SQLite schema has `chats` and `messages`. A request gets a server-generated `request_id`, then the user message and assistant message are inserted in separate short operations. A failure after the user insert intentionally leaves a user-only turn, but there is no durable request record, retry state, fingerprint check, or protection against two concurrent HTTP calls executing the same logical request. The existing `message_id` primary key alone does not prevent a retry from generating a different assistant ID and inserting a duplicate.

Gate A requires stronger behavior:

- one accepted logical request persists one user message;
- successful completion persists at most one assistant message and one replayable final response;
- duplicate calls with the same identity do not create duplicate messages;
- reuse of an idempotency identity with different content fails loud;
- no database transaction remains open during safety, retrieval, planning, rendering, or guards; and
- process crashes have deterministic recovery semantics.

The target is idempotent durable effects inside one SQLite database. It is not a claim that an HTTP response is delivered exactly once or that arbitrary external side effects run exactly once.

## Decision

**DECIDED:** Every accepted logical analyze operation has a durable request record with backend-generated `request_id`, required uniqueness on `(session_id, request_id)`, a request fingerprint, an observable state, version stamps, and a stored terminal payload when applicable. An approved client idempotency carrier needs a separate durable lookup mapping unless the owner explicitly changes the locked backend-ID authority.

### Required durable fields

The request record persists at least:

```text
session_id
request_id
idempotency_key_version  # nullable unless the approved distinct carrier is supplied
idempotency_key_digest   # nullable 64-hex digest; raw carrier is not stored
request_fingerprint
status
attempt_count
last_error_code
response_payload
contract_version
corpus_version
policy_version
prompt_version
retriever_version
generator_mode
created_at
updated_at
```

Gate A values include:

```text
prompt_version = "none"
generator_mode = "deterministic"
```

The physical schema must also preserve an unambiguous association with the resolved `chat_id`, the single user message, and the zero-or-one assistant message. Whether those links are columns on the preferred conceptual `analysis_requests` record or enforced through another reviewed relational design is addressed by the migration plan; they must not be inferred from message order.

### Database invariants

**DECIDED:** The database enforces:

```text
UNIQUE(session_id, request_id)
```

It must additionally enforce the logical cardinalities:

```text
one request -> exactly one persisted user message after Transaction A commits
one request -> zero or one persisted assistant message
one COMPLETE request -> exactly one stored final response payload
```

`message_id` uniqueness by itself is insufficient if retries allocate new IDs. The implementation plan must select a durable request-to-message linkage or reserve and reuse message IDs so these cardinalities are database-enforceable.

If the owner approves the recommended distinct idempotency header, the physical schema must additionally enforce one non-null hashed carrier per session, for example a partial `UNIQUE(session_id, idempotency_key_digest)`. This lookup constraint complements rather than replaces `UNIQUE(session_id, request_id)`: the client repeats the opaque carrier, while the backend generates and replays the public `request_id`. Raw carrier values are not logged or stored.

**OWNER_DECISION_REQUIRED:** Approve the exact physical linkage (for example, request foreign keys/unique constraints versus reserved message IDs stored with the request). The invariant is mandatory; the schema mechanism is not silently chosen by this ADR.

## Observable request state machine

**DECIDED:** The logical state machine is:

```text
RECEIVED
  -> PROCESSING
      -> COMPLETE
      -> FAILED_RETRYABLE
      -> FAILED_FINAL

FAILED_RETRYABLE
  -> PROCESSING
```

Gate A may physically combine `RECEIVED` and `PROCESSING`, but observable behavior must be equivalent. In the preferred short Transaction A, insert as `RECEIVED`, persist the user message, and transition to `PROCESSING` before one commit; another connection cannot observe an intermediate record without its user message.

### State definitions

| State | Durable meaning | Allowed next state |
|---|---|---|
| `RECEIVED` | Valid, ownership-checked logical request has been accepted inside the begin transaction but processing has not yet been made observable | `PROCESSING` only |
| `PROCESSING` | Request record and exactly one user message are durable; one attempt owns execution or is awaiting crash recovery | `COMPLETE`, `FAILED_RETRYABLE`, `FAILED_FINAL` |
| `COMPLETE` | Final guarded response, one assistant message, and response payload committed atomically | terminal |
| `FAILED_RETRYABLE` | No assistant was finalized; a recorded failure permits the same logical request to attempt again | `PROCESSING` |
| `FAILED_FINAL` | A safe final error is stored and this logical request must not execute again | terminal |

Transitions not listed above are invalid and must fail loud internally. In particular, `COMPLETE` and `FAILED_FINAL` never return to `PROCESSING`, and a retry never creates a second user message.

### Complete transition matrix

`NONE` below means no request record exists. It is not a persisted state.

| From | Event | Guard | To | Database effect | API/observable result |
|---|---|---|---|---|---|
| `NONE` | validation fails | Request violates frozen request schema | `NONE` | No chat/request/message write | Existing `invalid_request` behavior |
| `NONE` | ownership fails | Supplied chat is missing, deleted, or not owned by session | `NONE` | No request/message write | Existing indistinguishable `chat_not_found` behavior |
| `NONE` | new valid request | Ownership passed; unique key absent | `RECEIVED -> PROCESSING` | Transaction A inserts/checks request, creates/links owned chat if needed, inserts one user message, starts attempt, commits | Synchronous pipeline continues; no new public status is implied |
| `RECEIVED` | begin transaction completes | User message insert and request invariants succeeded | `PROCESSING` | Same Transaction A commit | Intermediate state is not externally observable when physically merged |
| `PROCESSING` | pipeline succeeds | Final response passes schema/evidence/output guards | `COMPLETE` | Transaction B inserts one assistant, stores response, marks complete, commits | Return normal frozen v1 response |
| `PROCESSING` | retryable pipeline failure | Failure class is approved retryable | `FAILED_RETRYABLE` | Failure transaction stores status/error/attempt data | Return the existing applicable safe error envelope; do not persist assistant |
| `PROCESSING` | final pipeline failure | Failure class is approved final | `FAILED_FINAL` | Failure transaction stores status/error/final error payload | Return stored safe final error; do not persist assistant |
| `PROCESSING` | process dies or lease becomes stale | Approved stale/recovery rule says no live attempt owns it | `FAILED_RETRYABLE` | Recovery transaction records retryable crash/interruption without inserting messages | Later identical request may retry |
| `FAILED_RETRYABLE` | identical retry | Same fingerprint and caller atomically wins transition | `PROCESSING` | Increment attempt exactly once; clear/retain prior error per approved audit policy; no new user message | Re-execute pipeline |
| `FAILED_RETRYABLE` | concurrent identical retry loses race | Another caller already moved state to `PROCESSING` | `PROCESSING` | No new write/message | In-progress outcome, subject to contract decision below |
| `COMPLETE` | identical duplicate | Same fingerprint | `COMPLETE` | Read only | Return stored response; pipeline does not execute |
| `PROCESSING` | identical duplicate | Same fingerprint and live/non-stale attempt | `PROCESSING` | Read only | In-progress outcome; pipeline does not execute |
| `FAILED_FINAL` | identical duplicate | Same fingerprint | `FAILED_FINAL` | Read only | Return stored final error; pipeline does not execute |
| any persisted state | same key, different fingerprint | Fingerprint mismatch | unchanged | Read/audit only; no message write | Key-reused outcome; never execute with changed payload |
| any state | invalid transition request | Transition not in this matrix | unchanged | Roll back and record internal diagnostic | Safe internal error handling; no invented public code |

Validation and ownership happen before idempotency persistence so attacker probes and invalid history are not written. Idempotency lookup is scoped by `session_id`, and follow-up ownership must be validated before any request state or response payload could be disclosed.

## Duplicate behavior

**DECIDED:** The duplicate decision table is exactly:

| Current state | Same fingerprint | Different fingerprint |
|---|---|---|
| `COMPLETE` | return stored response | `IDEMPOTENCY_KEY_REUSED` |
| `PROCESSING` | `REQUEST_IN_PROGRESS` | `IDEMPOTENCY_KEY_REUSED` |
| `FAILED_RETRYABLE` | retry without new user message | `IDEMPOTENCY_KEY_REUSED` |
| `FAILED_FINAL` | return stored final error | `IDEMPOTENCY_KEY_REUSED` |

If `RECEIVED` is physically visible, it behaves as `PROCESSING` for duplicates. The preferred atomic Transaction A makes that case unobservable.

`REQUEST_IN_PROGRESS` and `IDEMPOTENCY_KEY_REUSED` in this table are **architecture outcome labels**, not approved v1 `error.code` values. The frozen contract currently approves only `invalid_request`, `chat_not_found`, `retrieval_error`, `llm_error`, and `internal_error`.

**OWNER_DECISION_REQUIRED:** Product/API owners must approve:

- where the client supplies the idempotency identity (request field, header, or another explicit transport contract);
- whether that identity is named `request_id` or maps to the response `request_id`;
- the HTTP status and public error/envelope representation for in-progress and changed-fingerprint outcomes;
- whether request status is exposed at all; and
- whether replay returns the original response `request_id` or a per-transport-attempt ID is added elsewhere.

No implementation should map these outcomes to new public codes before that approval.

## Request identity gap in the frozen contract

The current `AnalyzeRequest` has `session_id`, optional `chat_id`, `question`, `user_type`, and `language`; it does not accept `request_id`. The server generates `request_id` after receiving the call. A server-generated per-attempt ID alone cannot deduplicate a first call and its retry because the client has no stable carrier to resend.

**DECIDED:** Gate A must not claim externally usable idempotency by generating a fresh key on every retry or by guessing from question text.

**PROPOSED:** Prefer a distinct client-supplied idempotency header. Store only its versioned digest for lookup; generate `request_id` in the backend; replay the original backend ID. This preserves the approved “backend owns IDs” boundary.

**OWNER_DECISION_REQUIRED:** The owner must resolve the transport-level identity before the idempotent `begin_request` behavior can be considered an approved API feature. Treating a client-supplied body `request_id` as the public response ID would transfer ID authority and therefore requires an explicit architecture/API exception, not merely a transport-schema edit. Any approved change follows the API contract review rule and updates machine artifacts consistently.

## Request fingerprint

### Direction

**DECIDED:** Fingerprint the canonical accepted request payload before semantic normalization.

The fingerprint is not computed from:

- the raw JSON byte stream, whose field order and escaping can differ without changing the request;
- accent-insensitive, lowercase, punctuation-stripped, or retrieval-normalized text, which can collapse materially different user input; or
- conversation history, corpus output, route decisions, or generated response, which are not part of the submitted payload.

### Canonical fields

The canonical object includes exactly the accepted input identity relevant to analysis:

```text
session_id
chat_id
question
user_type
language
contract_version
```

Rules:

1. Keys are serialized in stable lexicographic order.
2. JSON uses deterministic escaping and no insignificant whitespace, then UTF-8 encoding.
3. Unknown fields have already been rejected by request validation and are not silently ignored.
4. `session_id` is the validated exact value.
5. `chat_id` is the supplied chat ID. Missing and explicit null normalize to JSON `null`; for a new chat this remains null in the fingerprint even though Transaction A later creates a concrete chat.
6. Missing `user_type` normalizes to its contract default `"unknown"`; explicit `"unknown"` is therefore equivalent.
7. Missing `language` normalizes to its contract default `"vi"`; explicit `"vi"` is therefore equivalent.
8. `contract_version` is explicit (Gate A: `"v1"`).
9. `question` uses the exact accepted Unicode value after only contract-defined outer trimming/validation. It is encoded as UTF-8 without lowercasing, accent removal, punctuation collapse, internal whitespace collapse, or semantic normalization.
10. `request_id` itself is not inside its own fingerprint; it is the key whose reuse the fingerprint protects.

Example canonical shape:

```json
{"chat_id":null,"contract_version":"v1","language":"vi","question":"Tôi thuê nhà, chủ nhà giữ tiền cọc.","session_id":"session_001","user_type":"unknown"}
```

Choosing the exact accepted question rather than the semantic normalized question prevents one idempotency key from being reused for an accented/unaccented rewrite, changed punctuation that may alter meaning, or different substantive wording that happens to normalize to the same retrieval tokens. It also avoids treating irrelevant transport differences such as JSON field order as a changed request.

### Hash and storage

**DECIDED:** Compute SHA-256 over the canonical UTF-8 bytes and store `request_fingerprint` as 64 lowercase hexadecimal characters. The input contains no secret material added for hashing, and no hashing secret is introduced. The full user question is already governed by message persistence; the fingerprint should not be logged as a substitute for access controls.

Changing canonicalization or hash representation requires a new `fingerprint_version` and, when semantics require it, a new contract/policy version plus compatibility handling; it must not reinterpret existing rows silently.

## Schema bootstrap and migration order

**DECIDED:** Gate A startup has one unambiguous order. The existing SQLite adapter remains the owner of the legacy base schema, but its bootstrap becomes an explicit startup call rather than a constructor side effect. With foreign keys enabled and one short transaction, it accepts only either no base objects or the complete exact supported `chats`, `messages`, `idx_chats_session_updated`, and `idx_messages_chat_created` shape. It creates/verifies all four atomically only when absent. A partial or incompatible legacy base fails startup loudly and rolls back any bootstrap additions.

Only after that base transaction commits may the versioned request-schema migrator apply `001_analysis_requests`. The migration therefore declares foreign keys only after `chats` and `messages` exist with the reviewed shape; it does not rely on SQLite accepting references to absent tables. The `001` resource is DDL-only. The migrator alone enables FKs before its transaction, executes one `BEGIN IMMEDIATE`, preflights/applies/verifies the request shape, records the migration version, and commits. Request DDL, exact-shape acceptance, and version recording succeed or roll back together, with no nested transaction. A second startup is a no-op only after exact base and request shape verification.

No historical row is backfilled by this order. Changing the exact physical request linkage remains subject to the owner decision below; the startup ownership/order itself must not become ambiguous during implementation.

## Short transaction boundaries

**DECIDED:** The pipeline never holds an open database transaction while performing context construction, safety checks, routing, retrieval, evidence selection, decision, planning, rendering, guards, or final response validation.

### Transaction A: begin/check and persist user

One short atomic transaction performs:

1. idempotency insert/check under the approved logical-carrier mapping—recommended partial `UNIQUE(session_id, idempotency_key_digest)`—while retaining `UNIQUE(session_id, request_id)` for backend identity;
2. fingerprint comparison and duplicate-state decision;
3. for an accepted new-chat request, creation/linkage of the owned chat if needed;
4. insertion of exactly one user message for a new logical request;
5. transition to `PROCESSING` and exactly-once attempt-count update; and
6. commit.

A retry from `FAILED_RETRYABLE` performs the state/attempt update but does not insert another user message. Duplicate terminal/in-progress paths return their stored outcome without opening the pipeline.

### Pipeline execution

After Transaction A commits, the pipeline runs with no database transaction open. Durable request/message records are truth after commit; the request-scoped `AnalysisState` is authority only for the active execution.

### Transaction B: complete and persist assistant

After the final response has passed schema, evidence, and output-safety guards, one short atomic transaction performs:

1. verify the request is still owned by the expected `PROCESSING` attempt;
2. validate and insert the single assistant message using the attempt-local backend-generated candidate supplied with completion; that ID becomes durable only in this transaction;
3. store the final response payload;
4. mark the request `COMPLETE`; and
5. commit.

**DECIDED:** Assistant insertion, final-response storage, and `COMPLETE` update share this transaction. A state change that lost ownership or an assistant uniqueness conflict fails/rolls back rather than writing another assistant.

### Failure transaction

One short failure transaction performs:

1. verify the expected `PROCESSING` attempt;
2. mark `FAILED_RETRYABLE` or `FAILED_FINAL` according to the approved classification;
3. store `last_error_code` and, for a final failure, the replayable safe final error payload;
4. persist the attempt count/update timestamp without double-incrementing the attempt; and
5. commit.

No assistant message is inserted on a failure transition.

### Attempt count convention

**PROPOSED:** `attempt_count` counts started pipeline attempts. It starts at 1 when a new request enters `PROCESSING` and increments exactly once when an atomic retry wins `FAILED_RETRYABLE -> PROCESSING`. Failure/complete transactions retain that value; they do not increment it a second time.

## Crash and restart semantics

The crash rules are observable requirements, not best-effort cleanup.

| Crash point | Durable state after SQLite recovery | Required next behavior |
|---|---|---|
| After request insert, before user-message insert | Both writes are inside uncommitted Transaction A, so SQLite rolls back the request insert; no request/user row is durable | Identical retry behaves as the first accepted execution |
| After user message and Transaction A commit, before pipeline starts | `PROCESSING`, exactly one user message, no assistant | Recovery eventually marks stale work `FAILED_RETRYABLE`; retry runs without a new user message |
| During retrieval or any other pipeline stage | Same as above; no pipeline transaction is open | Same stale/retry behavior; partial `AnalysisState` is discarded |
| Before assistant persistence | `PROCESSING`, one user, no assistant | Same stale/retry behavior |
| After assistant insert but before `COMPLETE` within Transaction B | Assistant insert, response store, and state update are uncommitted and roll back together | Retry cannot observe a partial assistant; it may rerun after recovery |
| After Transaction B commit but before HTTP response delivery | `COMPLETE`, one user, one assistant, stored response | Identical retry returns the stored response without rerunning |
| During failure transaction before commit | Prior `PROCESSING` state remains after rollback | Stale recovery handles it; no assistant exists |
| After failure transaction commit | `FAILED_RETRYABLE` or `FAILED_FINAL` with stored error state | Follow duplicate table exactly |

Deleting a user-only partial turn to make the transcript look complete is rejected. The durable user message represents an accepted request; retry completes the same logical turn.

### Stale `PROCESSING` recovery

SQLite cannot know whether another process still owns a pipeline attempt. Recovery therefore needs a reviewed lease/staleness policy using durable timestamps/attempt ownership.

**OWNER_DECISION_REQUIRED:** Approve:

- the stale timeout;
- whether recovery is request-triggered, startup-scanned, or both;
- how a live worker lease/attempt token is represented;
- which process is allowed to transition stale `PROCESSING -> FAILED_RETRYABLE`; and
- the operator/audit signal for repeated crash recovery.

Until a record is demonstrably stale, an identical duplicate receives the in-progress outcome and must not start a second execution.

## Failure classification and client visibility

The state machine distinguishes a pipeline failure from a normal legal response:

- `unsupported`, `refuse_unsafe_request`, and `recommend_professional_help` are successful guarded responses and end in `COMPLETE`.
- `invalid_request` and `chat_not_found` occur before request/user persistence under the locked validation/ownership order.
- `retrieval_error` is an existing 503 dependency failure and is a natural retryable candidate.
- `llm_error` is an existing 503 dependency failure but is not reachable in deterministic Gate A; it matters only after a later model gate.
- `internal_error` cannot be globally classified as retryable or final without examining cause.

| Failure/outcome | Gate A classification | Client-visible | Notes |
|---|---|---:|---|
| Invalid request | Pre-persistence final | yes, existing contract | No request row or message |
| Ownership/chat not found | Pre-persistence final | yes, existing contract | No owner disclosure; no request row or message |
| Healthy no-source retrieval | Not a failure | normal success | Ends `COMPLETE` with cautious response |
| Safety refusal/escalation | Not a failure | normal success | Ends `COMPLETE` |
| Broken/unavailable corpus retrieval | Retryable candidate | yes, existing `retrieval_error` | Exact retry policy to be reviewed |
| SQLite busy/transient I/O | Retryable candidate | safe public envelope only | Must not expose raw SQLite details |
| Deterministic final schema/guard invariant violation | Final-or-retryable requires cause review | safe `internal_error` under current contract | Repeating blindly may never succeed |
| In-progress duplicate | OWNER_DECISION_REQUIRED | not defined by frozen contract | `REQUEST_IN_PROGRESS` is only an outcome label |
| Changed fingerprint/key reuse | OWNER_DECISION_REQUIRED | not defined by frozen contract | `IDEMPOTENCY_KEY_REUSED` is only an outcome label |

**OWNER_DECISION_REQUIRED:** Approve the exhaustive retryable/final classification and public behavior before implementation. Internal diagnostics may be richer than client-visible `last_error_code`; secrets, stack traces, SQL, and raw provider errors never enter the response payload.

## Exactly-once guarantees and limits

### What Gate A can guarantee

Within one healthy SQLite database, when every writer uses the defined transactions and constraints:

- at most one durable request record exists per `(session_id, request_id)`;
- one accepted logical request has exactly one user message after Transaction A commits;
- one completed logical request has exactly one assistant message and one stored response;
- concurrent identical calls allow one execution owner; duplicates follow state semantics;
- concurrent changed-payload reuse is rejected before any second message is written;
- a retry of `FAILED_RETRYABLE` does not append another user message; and
- a response lost after commit can be replayed from `COMPLETE`.

### What Gate A cannot guarantee

- HTTP response delivery exactly once: the server may commit and the client may time out.
- Pipeline execution exactly once: a process can crash after Transaction A and a later retry can execute the deterministic pipeline again.
- Exactly-once external side effects: future LLM billing, remote calls, notifications, or third-party writes need their own idempotency contracts.
- Guarantees across database deletion, restore to an older snapshot, corruption, or manual row edits.
- Guarantees across multiple backend instances using independent SQLite files.
- Guarantees for code paths that bypass the store port/constraints.
- Distributed consensus or production authentication; `session_id` remains the no-login MVP ownership boundary.

SQLite serializes short conflicting writes and enforces uniqueness in one database file; it is not a distributed idempotency service. Gate A's deterministic, side-effect-free analysis pipeline reduces retry variability but does not transform re-execution into exactly-once execution.

## Concurrency semantics

For concurrent calls with the same session and approved logical retry carrier (recommended: the same `idempotency_key_digest`):

1. Transaction A and the unique constraint determine the winner.
2. Same fingerprint: one caller creates/transitions the record; the other observes `PROCESSING` and does not execute.
3. Different fingerprint: the existing record remains unchanged and the changed-payload call receives the key-reused outcome.
4. Concurrent retries of `FAILED_RETRYABLE`: one atomic transition wins and increments the attempt; losers observe `PROCESSING`.
5. Completion verifies the winning attempt/lease before Transaction B writes.

In-memory locks may be an optimization but are not the correctness boundary; they do not protect multiple processes or restarts.

## Response payload and replay

`response_payload` stores the final contract-valid success response for `COMPLETE`, and a safe frozen-contract error envelope for `FAILED_FINAL`. Replay must not reconstruct a response from mutable current policy/corpus data because that would change the result and IDs for the same logical request.

The stored payload therefore preserves the original:

- `chat_id`, user and assistant message IDs;
- backend-owned domain/risk/decision/sources/safety notice/confidence/metadata;
- version stamps associated with execution; and
- response content that matches the persisted assistant `content_json`.

**OWNER_DECISION_REQUIRED:** Approve canonical JSON storage format, encryption/access expectations if any, retention, and the resolution of the current “request ID per API request” wording versus replay of one logical idempotent operation.

## Version stamps and trace boundary

The durable request record stores the listed final version stamps. Gate A uses `prompt_version="none"` and `generator_mode="deterministic"`. A retry of a logical request should not silently use a new policy/corpus/retriever version and then overwrite the identity of an earlier attempt.

**PROPOSED:** An in-progress retry continues with the versions pinned at first acceptance when those artifacts remain available. If they are unavailable/incompatible, transition to a safe reviewed failure rather than silently changing semantics.

Full `AnalysisState` and full stage traces are not persisted in Gate A. Durable request status/version/error information is persistence truth; redacted stage details belong to in-memory state and structured logs/trace sink.

## Consequences and trade-offs

### Positive consequences

- Network retries and double-clicks do not create duplicate chat turns.
- A completed response is replayable even when delivery acknowledgement is lost.
- Crash recovery has explicit state instead of guessing from adjacent messages.
- Transactions stay short, reducing SQLite lock duration.
- Version stamps make a persisted answer auditable without persisting the full runtime state.
- Changed-payload key reuse is detected rather than silently returning an unrelated stored answer.

### Costs and limitations

- A new request record/schema migration and request-to-message linkage are needed.
- The frozen API needs an owner decision to carry a stable client-resubmittable identity and represent duplicate outcomes.
- `PROCESSING` needs lease/stale recovery governance.
- The system retains user-only accepted turns during retryable failures; UI may need a product-approved way to represent them.
- Response payload storage duplicates some assistant content but is necessary for exact replay.
- Deterministic replay and version pinning add lifecycle requirements when corpus/policy versions change.

## Rejected alternatives

1. **Use a server-generated request ID created independently on every HTTP attempt.** Rejected because retries cannot identify the same logical operation.
2. **Use `(chat_id, normalized_question)` as the idempotency key.** Rejected because legitimate repeated questions would collide and semantic normalization can collapse materially different text.
3. **Hash the raw JSON bytes.** Rejected because field order/escaping differences would produce false mismatches.
4. **Fingerprint semantically normalized question text.** Rejected because case, accents, punctuation, or wording changes may be material and must not reuse the key silently.
5. **Hold one database transaction open across the entire pipeline.** Rejected because retrieval/generation latency would hold locks and amplify contention/failure impact.
6. **Commit the assistant insert and `COMPLETE` update separately.** Rejected because a crash can leave a visible assistant attached to a non-complete request and allow duplication.
7. **Delete the persisted user message after a pipeline failure.** Rejected because it loses the accepted request and breaks retry/audit semantics.
8. **Rely only on frontend duplicate-submit blocking or in-memory locks.** Rejected because multi-tab, multi-process, restart, and network retries bypass them.
9. **Claim exactly-once pipeline execution.** Rejected because crash recovery can legitimately re-execute work after Transaction A.
10. **Return the latest regenerated answer on a `COMPLETE` duplicate.** Rejected because idempotent replay must return the stored result, not current mutable policy output.
11. **Invent public duplicate error codes inside implementation.** Rejected because the frozen v1 error contract has not approved them.

## Owner decisions and deferred work

| Item | Marker | Required outcome |
|---|---|---|
| Logical states and transitions | DECIDED | Preserve the full observable state machine |
| Duplicate table | DECIDED | Same fingerprint replays/waits/retries; changed fingerprint fails loud |
| Short Transaction A/B/failure boundaries | DECIDED | No transaction across pipeline; assistant + response + COMPLETE atomic |
| `UNIQUE(session_id, request_id)` | DECIDED | Database-enforced |
| Fingerprint direction/hash | DECIDED | Canonical accepted payload, SHA-256, lowercase hex |
| Idempotency key transport/name | OWNER_DECISION_REQUIRED | Prefer a distinct header mapped by versioned digest to a backend-generated `request_id`; client-owned public request IDs require an explicit authority exception |
| Public in-progress/key-reused behavior | OWNER_DECISION_REQUIRED | Approve HTTP/envelope/code; labels here are not codes |
| Request-status exposure | OWNER_DECISION_REQUIRED | Keep internal or approve a contract change |
| Physical request-message uniqueness mechanism | OWNER_DECISION_REQUIRED | Select schema design that enforces one user/assistant per request |
| Stale `PROCESSING` timeout/recovery owner | OWNER_DECISION_REQUIRED | Approve lease and restart behavior |
| Exhaustive retryable/final error classification | OWNER_DECISION_REQUIRED | Map existing errors without leaking internals |
| `response_payload` format/retention | OWNER_DECISION_REQUIRED | Approve canonical form, validation, access, retention, compatibility, and rollback |
| Historical chat/message migration | OWNER_DECISION_REQUIRED | Review the implementation plan's proposed additive table and no-backfill policy; do not silently grant retroactive idempotency |
| Distributed/multi-database exactly-once | DEFERRED | Not provided by Gate A SQLite design |
| External side-effect idempotency | DEFERRED | Required only when later gates add such effects |

## Compliance note

This ADR defines a target persistence contract only. It does not alter SQLite, add a migration, change API schemas/error codes, implement ports, start a backend, or modify tests.
