# ADR-004: Evidence Plan Boundary

- **Status:** PROPOSED — planning-only; owner review required before implementation
- **Scope:** Gate A deterministic vertical slice and the later Gate F wording boundary
- **Depends on:** `docs/api_contract.md`, `docs/ai_core_spec.md`, `docs/rag_spec.md`, `docs/safety_policy.md`, ADR-002, ADR-003
- **Supersedes:** nothing

## Decision markers

This ADR uses the following markers so that a planning statement is not mistaken for an approved product-contract change:

- **DECIDED:** locked by the approved architecture prompt or frozen MVP specifications.
- **PROPOSED:** implementation direction that can be changed during owner review without changing the locked boundary.
- **OWNER_DECISION_REQUIRED:** must be decided before code depending on it is written.
- **DEFERRED:** explicitly outside Gate A.

## Context and problem

The existing MVP contract exposes structured answer fields and approved source objects, while the current `backend_lite` generator produces those answer fields directly from deterministic templates. A later wording model could improve prose, but it must not acquire authority to add advice, strengthen a cautious point, reorder required safety guidance, or cite evidence that the backend did not select.

The architecture therefore needs an internal boundary between:

1. retrieved and selected evidence;
2. backend-authorized guidance content;
3. rendered user-facing wording; and
4. the frozen API response.

Without that boundary, a generator can silently turn retrieval candidates into legal conclusions. With an overly strong claim about the boundary, the system could also imply that structural source linkage proves legal correctness. It does not.

## Decision

**DECIDED:** The backend creates an authoritative, deterministic `AnswerPlan`. The plan is the complete allow-list of user-facing guidance points for one analysis execution. Rendering consumes that plan; rendering does not make legal, safety, source, risk, decision, identity, or metadata decisions.

The minimum point contracts are:

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

`GuidancePoint` belongs to the backend-owned `AnswerPlan`. `RenderedPoint` belongs to the rendering result. Neither type is an approved addition to the public API; both are internal planning contracts.

### Authority chain

The data direction is:

```text
RetrievalResult
  -> EvidenceBundle (selected approved source objects)
  -> backend decision and safety policy
  -> deterministic AnswerPlan[GuidancePoint]
  -> rendered points
  -> structural guards
  -> backend finalization
  -> existing AnalyzeResponse fields
```

The following invariants apply:

- Every `supporting_source_ids` value is drawn from the request's selected `EvidenceBundle`, never from the full corpus or model output.
- Source objects remain backend-owned and are mapped from the curated corpus. The plan contains source IDs, not model-created source objects.
- A point may intentionally have no source only when policy permits cautious, procedural, clarification, refusal, escalation, privacy, or product-boundary text without claiming legal authority.
- A point with no adequate supporting evidence cannot be marked `strong`.
- Safety refusal, high-risk escalation, no-source caveats, and important legal checklists are authored as deterministic plan points in the MVP.
- The backend-owned `domain`, `risk_level`, `decision`, `confidence`, `sources`, `safety_notice`, IDs, and metadata never come from rendering.

## Gate A boundary

**DECIDED:** Gate A uses no LLM and no embeddings. Both the `AnswerPlan` and rendered output are deterministic.

For Gate A:

- policy code/templates create all `GuidancePoint` values;
- the deterministic renderer normally emits `RenderedPoint.text == GuidancePoint.canonical_text` or a deterministic locale/template transformation;
- high-risk guidance, refusals, escalation copy, evidence-preservation guidance, and legally important checklists remain deterministic;
- the evidence/output guards run before finalization and assistant persistence;
- only the final guarded, validated response is persisted;
- `point_id`, `strength`, and plan internals are not added to the frozen `AnalyzeResponse` unless a separately approved contract change says otherwise;
- the existing public arrays (`clarifying_questions`, `checklist`, `next_steps`) and `summary` remain the transport shape.

Gate A does not claim that its 26-snippet corpus covers Vietnamese law, that a linked source supports every phrase, or that deterministic text is legally correct.

### Gate A mapping to the frozen response

**PROPOSED:** `AnswerPlan` groups points by an internal section enum corresponding to `summary`, `clarifying_questions`, `checklist`, and `next_steps`. The section is plan structure outside the minimal `GuidancePoint` type shown above; it must not be inferred from free text.

**OWNER_DECISION_REQUIRED:** Before implementation, the owner must approve the exact internal mapping representation and stable `point_id` catalogue. This decision must preserve the existing response shape and reload equivalence. It must not introduce new public fields by implication.

## Later Gate F boundary

**DEFERRED:** Gate F may introduce an LLM only as a wording renderer. Its input is the already-authorized plan, and its output is a list of `RenderedPoint`; it does not receive authority to create the final response.

Gate F must enforce all of the following after parsing model output:

1. `draft point IDs ⊆ allowed plan point IDs`;
2. no unknown IDs;
3. no duplicated IDs;
4. every required point is present;
5. strength cannot be elevated;
6. final order follows `AnswerPlan` order, regardless of model output order.

Additional consequences of those rules:

- Missing optional points may only be dropped when the plan marks them optional; absence is never inferred from model silence.
- A model cannot merge two points under one ID if that would hide a required point.
- A model cannot split one plan point into new IDs.
- A model-provided `point_id`, source ID, section, strength, or order is untrusted input until the structural guard validates it.
- On parse or structural failure, the system falls back to deterministic plan rendering rather than returning partial model text.
- The finalizer rebuilds ordering and backend-owned fields from the plan and authoritative analysis state, not from model serialization.

**OWNER_DECISION_REQUIRED:** Gate F needs an approved definition of wording-equivalence and strength-elevation review. ID containment alone cannot detect a paraphrase that changes legal meaning. Until that decision and its tests exist, a wording model is not eligible for high-risk or legally important checklist points.

## What the boundary proves

**DECIDED:** Structural grounding is enforceable. The system can automatically establish that:

- every rendered point corresponds to an allowed plan point;
- required points are present exactly once and in the planned order;
- cited IDs come from selected evidence;
- a renderer did not introduce a new point ID or explicitly raise its declared strength; and
- backend-owned response fields were finalized outside the renderer.

**DECIDED:** Legal correctness and semantic entailment are not automatically certified. Specifically, the boundary does not prove that:

- a source is legally current or correctly interpreted;
- a cited source supports the guidance point;
- `canonical_text` is legally correct;
- a Gate F paraphrase preserves every legal qualification; or
- a `strong` point is substantively justified.

Those questions require reviewed corpus governance, policy review, evaluation evidence, and where appropriate a qualified legal reviewer.

## Plan and guard invariants

The implementation plan must test these invariants before any later wording model is considered:

| Invariant | Gate A behavior | Gate F behavior |
|---|---|---|
| Stable point identity | Deterministic catalogue/key | Renderer must echo an allowed ID |
| Evidence containment | `supporting_source_ids` subset of selected evidence | Renderer cannot add source IDs |
| Required content | Plan construction fails loud if required policy points are absent | Draft missing a required ID is rejected |
| Duplicate content identity | Duplicate `point_id` rejected | Duplicate returned ID rejected |
| Ordering | Deterministic plan order | Finalizer restores plan order |
| Strength | Assigned by backend policy | Renderer cannot elevate it |
| High-risk/checklist wording | Deterministic | Remains deterministic until separately promoted |
| Failure fallback | Deterministic render | Deterministic render, never raw model output |

`EvidenceGuard` is therefore a structural-containment guard. It is not named or reported as a legal-correctness verifier.

## Consequences and trade-offs

### Positive consequences

- Safety and decision authority remain inspectable and testable outside a model.
- Source identity can be checked independently from prose generation.
- Deterministic Gate A output supports repeatable persistence, reload equivalence, and idempotent replay.
- Gate F can be added without changing the public API or giving the model ownership of sources and decisions.
- A failed renderer has a safe deterministic fallback.

### Costs and limitations

- Product and policy owners must maintain a point catalogue and deterministic copy.
- The renderer has less freedom and may sound repetitive.
- Point-level structural checks do not solve semantic entailment.
- Stable IDs become governed internal artifacts and cannot be casually renamed once referenced by tests or persisted response plans.
- Mapping point-level provenance onto the current section-based API loses some provenance detail at the client boundary unless the contract is later changed.

## Rejected alternatives

1. **Let the LLM generate the final structured response.** Rejected because it would give the model authority over decisions, sources, metadata, IDs, and required safety content.
2. **Let the LLM emit arbitrary prose and run only a final keyword safety scan.** Rejected because a scan cannot prove that required guidance exists or that new advice was not added.
3. **Treat a source ID attached to a point as proof of legal support.** Rejected because identity and structural linkage do not establish entailment or correctness.
4. **Use free-text matching instead of stable `point_id` values.** Rejected because wording changes make containment, duplication, and ordering ambiguous.
5. **Allow Gate F wording for high-risk guidance immediately.** Rejected for MVP; high-risk and important legal checklist text remains deterministic until separately reviewed and promoted.
6. **Expose plan internals in the v1 API during Gate A.** Rejected because the frozen API does not require them and Gate A must avoid contract drift.

## Owner decisions and deferred work

| Item | Marker | Required outcome |
|---|---|---|
| Deterministic plan and rendering in Gate A | DECIDED | Implement without an LLM |
| Structural Gate F containment rules | DECIDED | All six locked rules are mandatory |
| Stable `point_id` generation/catalogue | OWNER_DECISION_REQUIRED | Approve naming, versioning, and rename policy before coding |
| Internal section-to-v1-response mapping | OWNER_DECISION_REQUIRED | Choose representation without public contract drift |
| Wording-equivalence/semantic-strength review | OWNER_DECISION_REQUIRED | Required before any Gate F promotion |
| LLM wording renderer | DEFERRED | Gate F only |
| Semantic NLI/entailment guard | DEFERRED | Not Gate A and not a substitute for legal review |
| Public point-level provenance | DEFERRED | Requires an explicitly approved API version/change |

## Compliance note

This ADR defines architecture only. It does not implement models, generators, guards, migrations, tests, or API changes.
