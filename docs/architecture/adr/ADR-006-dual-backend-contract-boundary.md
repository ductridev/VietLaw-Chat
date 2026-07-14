# ADR-006: Dual-Backend Contract Boundary

- **Status:** PROPOSED — planning-only; owner review required before implementation
- **Scope:** `backend/` production implementation and `backend_lite/` owner-controlled fallback implementation
- **Depends on:** `docs/api_contract.md`, frozen product specifications, corpus format, evaluation system
- **Supersedes:** any informal assumption that one backend is an implementation library or legal ground truth for the other

## Decision markers

- **DECIDED:** locked by the approved architecture prompt or frozen MVP specifications.
- **PROPOSED:** reviewable enforcement direction.
- **OWNER_DECISION_REQUIRED:** approval is needed before changing contract authority or build/release governance.
- **DEFERRED:** explicitly outside Gate A.

## Context and problem

VietLaw-Chat has two backend implementations with different ownership and operational purposes:

```text
backend/        # production backend owned by the teammate
backend_lite/   # deterministic fallback backend controlled by the owner
```

The implementations must agree on externally observable product behavior without becoming coupled through a shared business implementation. Sharing business code would make the fallback unable to detect production-implementation drift and would blur ownership. Allowing each backend to invent its own API semantics would make frontend and evaluation results incomparable.

The correct boundary is shared contracts and data formats, not shared classifiers, policies, generators, retrieval algorithms, persistence implementations, or orchestration code.

## Decision

**DECIDED:** The two backends are independent implementations.

- Neither backend imports business code from the other.
- Neither backend writes or migrates the other backend's database.
- They do not share an internal business-logic package.
- Concrete adapters, policies, pipeline stages, and persistence code remain inside their owning backend.
- They share normative API semantics, machine contract artifacts, corpus format, and evaluation definitions.
- They are started, versioned, deployed, and evaluated separately.
- A green `backend_lite` result does not make `backend/` green; a production result does not bless `backend_lite`.
- Neither backend is legal ground truth for the other. Reference-assisted differential testing remains diagnostic unless separately promoted.

The backend/LLM authority boundary applies independently in both implementations:

- backend owns `domain`, `risk_level`, `decision`, `confidence`, `sources`, `safety_notice`, IDs, and metadata;
- an LLM, if introduced after Gate A, owns wording only.

## Shared contract artifacts

The allowed shared boundary is:

| Artifact | Authority | Consumption rule |
|---|---|---|
| `docs/api_contract.md` | Normative product semantics | Humans and implementations use it to resolve endpoint/field/behavior meaning |
| `contracts/openapi.json` | Machine-enforced HTTP/API shape artifact | Both backends and frontend tooling validate against the same reviewed version |
| `contracts/generated/*.schema.json` | Machine-enforced JSON payload artifacts | Tests validate request, response, error, chat, and internal exported shapes as applicable |
| Evaluation cases/configuration | Shared observable acceptance definitions | Each backend is tested independently over HTTP; evaluator does not import backend business logic |
| Corpus schema/format | Shared retrievable-evidence data contract | Each backend may implement its own loader/retriever but reads the same approved format/version |

**DECIDED:** `docs/api_contract.md` is authoritative for normative product semantics. OpenAPI and JSON Schema are machine-enforced artifacts. A generated schema is not permitted to silently redefine product meaning.

If prose semantics and a machine artifact disagree, that is contract drift to resolve through owner review. Runtime teams must not choose whichever version makes their implementation pass.

### Current repository qualification

At this planning baseline, `docs/api_contract.md` exists and is frozen. The target `contracts/openapi.json` and `contracts/generated/*.schema.json` paths are architecture artifacts named by the approved prompt; their creation/generation is not performed by this ADR. Their absence must not be described as an already-enforced machine boundary.

**OWNER_DECISION_REQUIRED:** The owner must approve the authoritative generation direction and review workflow for the machine artifacts before implementation. The normative rule remains fixed: generated artifacts enforce shape; they do not override the approved semantics document.

## Dependency direction

The permitted dependency direction is:

```text
frontend/evaluator
      |
      v
shared normative + machine contracts
      ^                         ^
      |                         |
backend/ public HTTP      backend_lite/ public HTTP
      |                         |
backend-owned code        lite-owned code
      |                         |
backend-owned storage     lite-owned SQLite storage
```

The evaluator observes both over HTTP. Corpus files and schemas are read-only input contracts at this boundary. No arrow exists from one backend's business layer into the other.

### Forbidden dependency examples

- `backend_lite` importing a classifier, retriever, prompt, store, model, or service from `backend`;
- `backend` importing fallback templates, guards, stores, or runtime state from `backend_lite`;
- a `shared/` package containing domain, safety, decision, confidence, retrieval, generation, or finalization business logic;
- one backend opening the other's runtime SQLite file;
- an evaluator importing backend internals to calculate expected answers;
- copying a backend response as the legal golden answer for the other.

### Allowed reuse

- generated client/server types derived from approved machine artifacts;
- JSON Schema validation utilities that contain no product decision logic;
- the public corpus schema and approved corpus files;
- constants whose only source is an approved contract artifact, when generated rather than independently reinterpreted;
- generic third-party libraries; and
- shared evaluation cases, thresholds, reporters, and black-box clients.

Any proposed shared module that answers “what should this legal request do?” is business logic and is outside the allowed boundary.

## Gate A boundary

**DECIDED:** Gate A changes only the fallback vertical slice planned for `backend_lite`; it does not refactor or implement the teammate's `backend/` and does not create a shared business package.

Gate A must:

- preserve the existing frozen API semantics;
- keep `backend_lite` composition and adapters within its package;
- use the shared 26-snippet corpus format without changing corpus content;
- run shared legacy/smoke/MVP evaluation against `backend_lite` as its own target;
- produce exact failure reports rather than weakening shared cases to fit the fallback; and
- keep frontend compatibility through the public API, not through imports.

Gate A may define a plan for machine contract artifacts and drift tests. If creating/generating those artifacts would expand the approved Gate A implementation scope, that work remains proposed or deferred until the owner explicitly includes it.

**OWNER_DECISION_REQUIRED:** A new idempotency header is shared public transport semantics, even if Backend Lite implements it first. The shared frontend must remain carrier-disabled by default until either (a) every configured backend/proxy accepts the approved header and its browser CORS preflight, proven independently over HTTP, or (b) an explicitly approved fallback-only capability/configuration prevents the header from reaching an unsupported production target. Gate A does not implement `backend/` to force parity and does not enable a global frontend header based only on a green fallback test.

**DECIDED:** The Gate A plan does not require the reviewed MVP suite to become green. It requires the suite to run and report exact failures. Safety blockers belong to Gate B rather than being hidden through contract changes.

## Later enforcement

**PROPOSED:** CI should include a contract-drift test that:

1. validates `contracts/openapi.json` and each generated JSON Schema;
2. compares generated artifacts to their approved source/version;
3. verifies each backend's public OpenAPI/response shapes against the shared artifacts;
4. runs backend-independent contract cases over HTTP; and
5. fails when either implementation changes required fields, enums, error envelopes, ownership behavior, or source shapes without an approved contract update.

**DEFERRED:** This CI drift test is not implemented by this planning pass and is not silently added to Gate A when outside the approved implementation scope.

Contract evolution requires:

- a documented semantic change in `docs/api_contract.md`;
- product/frontend-owner and backend/AI-core-owner approval under the frozen review rule;
- regenerated and reviewed machine artifacts;
- compatibility/migration notes;
- separate tests against both backends; and
- explicit versioning when the change is not additive/backward compatible.

## Evaluation boundary

Shared evaluation means common cases and oracles, not common implementation.

- Each backend gets its own run ID, reports, pass/fail decision, and environment/version stamps.
- Source identity is checked against the corpus; it is not a claim of legal correctness.
- A differential comparison can classify divergences, but a reference backend limitation cannot automatically become a candidate regression.
- Candidate normal contract/source/safety oracles remain binding in a differential diagnostic.
- Load/capacity results apply only to the target/environment measured.
- `backend_lite` remains a deterministic fallback/reference for UI and contract work, not the production service and not an oracle for substantive law.

## Consequences and trade-offs

### Positive consequences

- The fallback remains a meaningful independent implementation and test target.
- Frontend integration depends on a stable public contract rather than implementation ownership.
- Production can evolve its internal architecture without importing fallback code.
- Contract drift becomes detectable at machine and black-box boundaries.
- A defect shared by both implementations is still detectable by normal oracles rather than being normalized as expected behavior.

### Costs and limitations

- Some orchestration/policy code may be duplicated deliberately.
- Both teams must update their implementations when an approved contract changes.
- Contract artifact generation and drift review add governance work.
- Independent implementations can differ in quality and performance while remaining shape-compatible.
- Shared schemas cannot enforce substantive legal correctness or internal dependency inversion.

## Rejected alternatives

1. **Create a shared business-logic package for both backends.** Rejected because it destroys implementation independence and makes shared defects harder to detect.
2. **Make `backend_lite` import and wrap production services.** Rejected because fallback availability and ownership would depend on production implementation.
3. **Treat production OpenAPI output as the sole contract.** Rejected because implementation output cannot silently replace normative product semantics.
4. **Let each backend own a separate API schema.** Rejected because frontend and evaluation behavior would diverge.
5. **Use differential equality with `backend_lite` as the release gate.** Rejected because fallback behavior is not legal ground truth and may itself have known limitations.
6. **Share a database between implementations.** Rejected because schemas, lifecycle, tests, and failures would interfere across ownership boundaries.
7. **Claim contract enforcement before machine artifacts/drift tests exist.** Rejected because architecture intent is not operational evidence.

## Owner decisions and deferred work

| Item | Marker | Required outcome |
|---|---|---|
| Independent business implementations | DECIDED | No cross-imports or shared business package |
| Normative semantics authority | DECIDED | `docs/api_contract.md` |
| Machine artifact role | DECIDED | OpenAPI/JSON Schema enforce shape, not product meaning |
| Independent evaluation | DECIDED | Separate result per backend |
| Machine-artifact generation direction/tooling | OWNER_DECISION_REQUIRED | Approve before generating or enforcing artifacts |
| Which artifact changes are Gate A scope | OWNER_DECISION_REQUIRED | Do not expand Gate A implicitly |
| Shared frontend idempotency-header rollout | OWNER_DECISION_REQUIRED | Enable only after every selected HTTP target/proxy passes header and CORS checks, or behind an approved target-scoped fallback capability; do not plan production implementation here |
| CI contract-drift implementation | DEFERRED | Proposed for a later approved pass if outside Gate A |
| Shared business-logic package | DECIDED | Prohibited |
| Production-backend refactor | DEFERRED | Teammate-owned and outside fallback Gate A |

## Compliance note

This ADR does not create contract artifacts, edit either backend, add a shared package, change CI, or run/mutate production services.
