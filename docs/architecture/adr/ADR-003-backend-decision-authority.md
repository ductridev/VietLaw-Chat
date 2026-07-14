# ADR-003: Backend Decision Authority and Wording Boundary

- **Status:** PROPOSED — ready for architecture review; planning-only
- **Scope:** authority for classification, safety, evidence, decision, confidence, final response fields, and any future wording model
- **Depends on:** `docs/api_contract.md`, `docs/ai_core_spec.md`, `docs/rag_spec.md`, `docs/safety_policy.md`, ADR-001, ADR-002, ADR-004
- **Supersedes:** any design in which a generator/model or frontend determines final legal-navigation behavior

## Decision markers

- **DECIDED:** locked by approved architecture or frozen MVP semantics.
- **PROPOSED:** internal design direction that remains reviewable.
- **OWNER_DECISION_REQUIRED:** a product/policy choice that must be approved before dependent coding.
- **DEFERRED:** outside Gate A.

## Context and problem

The public response combines user-facing language with fields that control legal-navigation behavior. If a single generator owns both, fluent wording can silently change safety, risk, sources, or the response mode. This is unacceptable even when the generator is deterministic, and it becomes a larger risk if an LLM is added later.

The current fallback backend already enforces much of the intended boundary:

- `backend_lite/app/schemas/content.py::GeneratedContent` permits only `summary`, `clarifying_questions`, `checklist`, `next_steps`, and `used_source_ids`, with extra fields forbidden.
- `LiteDomainClassifier`, `LiteRiskClassifier`, and `LiteDecisionPolicy` calculate backend values.
- `LiteCitationGuard` filters source IDs to retrieved IDs.
- `LiteSafetyGuard` can detect unsafe generated clauses and replace them with a stricter result; it is escalation-only.
- `LiteResponseBuilder` maps approved source objects and creates `AnalyzeResponse` with backend IDs, classification, notice, confidence, and metadata.

There are also target gaps:

- `PatternUnsafeDetector` returns `expected_decision`, and `AgentRuntime` writes that value into classification state before `LiteDecisionPolicy`; safety detection and response decision authority are therefore not cleanly separated.
- `GeneratedContent.used_source_ids` lets the generator participate in source selection, even though the IDs are later constrained. The locked target makes evidence selection a backend policy before rendering.
- there is no standalone `ConfidenceCalculator`; confidence constants are embedded in `LiteResponseBuilder`.
- current policy classes read the broad mutable `AgentState`, rather than returning narrow typed results applied by one orchestrator.

This ADR preserves the working backend-owned boundary while separating observations, policy decisions, rendering, guards, and finalization.

## Decision

**DECIDED:** the backend is the only authority for:

- `domain`;
- `risk_level`;
- `decision`;
- `confidence`;
- `sources`;
- `safety_notice`;
- request, chat, and message IDs; and
- all metadata.

**DECIDED:** a generator owns wording only. Gate A has no LLM and uses a deterministic generator. If a later gate adds an LLM, the model remains a renderer of backend-authorized plan points; it does not become a classifier, safety policy, evidence selector, decision maker, confidence estimator, ID generator, metadata producer, or response finalizer.

## Authority chain

The normative backend authority chain is:

```text
SafetyPolicy
  -> RoutingPolicy
  -> ResponseDecisionPolicy
  -> ConfidenceCalculator
  -> ResponseFinalizer
```

Evidence selection, answer planning, rendering, and guards feed this chain without replacing it:

```text
current turn -> SafetyPolicy -> RoutingPolicy -> ResponseDecisionPolicy
corpus -> lexical retrieval -> EvidenceSelector ---------|
                                                        v
                                     deterministic AnswerPlan
                                                        |
                                                        v
                                         wording-only renderer
                                                        |
                                                        v
                                  schema/evidence/output-safety guards
                                                        |
                                                        v
                                         ConfidenceCalculator
                                                        |
                                                        v
                                           ResponseFinalizer
```

`ResponseFinalizer` consumes post-guard authority. It must never read stale pre-guard domain, risk, decision, content, or source values.

### `SafetyPolicy`

`SafetyPolicy` classifies the exact current turn and returns typed facts and constraints, including:

- whether harmful intent is present;
- whether the legal situation is high risk without harmful intent;
- safety category and stable policy flags;
- a minimum risk/domain constraint where the frozen policy requires it;
- forbidden response capabilities; and
- whether a refusal or escalation is mandatory as a policy constraint.

It does not produce normal legal guidance, source selection, confidence, metadata, or the final public `decision` for every request. A mandatory constraint is mapped to the public decision by `ResponseDecisionPolicy`.

The existing `PatternUnsafeDetector.expected_decision` should therefore become a safety constraint/reason code rather than a mutable public decision value. This is a target migration; no current file is claimed to have changed.

### `RoutingPolicy`

`RoutingPolicy` uses normalized current-turn input, the safety result, and Gate A's minimal same-chat context to produce backend-owned domain/topic candidates and legal-risk factors.

It must:

- give current-turn harmful/high-risk signals priority over context;
- preserve the frozen rule that harmful intent is exposed as `domain: high_risk`;
- distinguish a victim/report of danger from intent to cause harm;
- keep missing facts separate from legal risk; and
- avoid using retrieval candidates as classification truth.

Routing may identify candidates and reasons. It does not render an answer or decide evidence adequacy.

### `ResponseDecisionPolicy`

`ResponseDecisionPolicy` is the sole normal authority that maps safety constraints, selected route, risk factors, fact sufficiency, and evidence adequacy to the frozen public decision enum:

- `answer_with_guidance`;
- `ask_clarifying_questions`;
- `recommend_professional_help`;
- `refuse_unsafe_request`; or
- `unsupported`.

Its typed `DecisionRecord` contains at least final `domain`, `risk_level`, `decision`, evidence/fact-sufficiency categories, and stable backend reason codes. It is stored in `AnalysisState.decision`; it is not accepted from a generator.

`ResponseDecisionPolicy` does not create wording. It selects the deterministic plan mode and required plan points.

### `ConfidenceCalculator`

`ConfidenceCalculator` derives the three frozen confidence fields—`domain`, `risk`, and `answer`—from backend facts such as deterministic match strength, policy signals, evidence adequacy, no-source status, and guard outcomes.

Confidence:

- is bounded to `[0, 1]`;
- is not a probability of legal correctness or likely court outcome;
- is lower for no-source, fallback, or guard-corrected content;
- cannot be supplied or raised by a generator; and
- is debug/internal metadata that the frontend must not present as legal certainty.

Exact calibration remains an owner-reviewed implementation decision. Moving current constants out of `LiteResponseBuilder` must not imply that a statistical model is required.

### `ResponseFinalizer`

`ResponseFinalizer` is the only final response constructor. It:

- uses the authoritative post-guard domain/risk/decision;
- attaches backend-generated request/chat/message IDs;
- maps the backend-selected evidence bundle to corpus-faithful `SourceObject` values;
- attaches the exact backend constant `safety_notice`;
- attaches calculated confidence and backend metadata/version stamps;
- maps guarded rendered points to the frozen response sections;
- validates the complete `AnalyzeResponse`; and
- yields the exact candidate later stored by the completion transaction.

It cannot retrieve, classify, invoke a model, or invent sources. `LiteResponseBuilder` is the current closest anchor, but the target finalizer consumes `AnswerPlan`/guard results and an external confidence result rather than calculating policy implicitly.

## Three conditions that must remain separate

### Harmful intent

Harmful intent is a request to enable evasion, forgery, deception, threats/coercion, evidence hiding/deletion/destruction, or a comparable prohibited act.

Required result:

- `domain: high_risk`;
- `risk_level: high`;
- normally `decision: refuse_unsafe_request`;
- a brief deterministic refusal and lawful redirection; and
- no actionable detail, even if relevant normal-topic sources exist.

### Legal high risk

Legal high risk describes a serious situation without a request for harmful assistance: for example a police summons, fatal/injury accident, being threatened or assaulted, or another serious legal exposure.

Required result:

- `domain: high_risk` and `risk_level: high` where required by frozen policy;
- normally `decision: recommend_professional_help`;
- safe general preparation, urgent safety steps where applicable, and escalation; and
- no tactical statement, evasion, retaliation, or evidence advice.

High risk is not automatically harmful intent. A person reporting a threat must not be refused as if they requested a threat.

### Insufficient facts or evidence

Insufficient facts/evidence is a coverage condition, not proof of danger or wrongdoing.

- Missing material facts normally leads to `ask_clarifying_questions` without automatically increasing risk.
- A healthy retrieval result with no adequate source leads to `sources: []` and cautious deterministic content, clarification, or a supported general escalation.
- The backend must not fabricate a source or strong legal conclusion to avoid an empty source panel.
- A no-source result does not by itself force `unsupported`; the response depends on scope, facts, and risk.

## Required situation-to-behavior matrix

| Situation | Safety classification | Evidence treatment | Required backend behavior |
| --- | --- | --- | --- |
| Evasion, forgery, threats/coercion, evidence hiding/deletion/destruction | harmful intent | safety-only evidence or none; never normal how-to evidence | refuse briefly and redirect lawfully |
| Police summons, fatal/injury accident, victim of violent threat | legal high risk, not necessarily harmful | relevant safe preparation/escalation evidence or cautious no-source | safe general guidance plus professional/authority escalation |
| Lawful request with insufficient facts | safe/normal unless separate risk signal exists | do not infer evidence from history | ask focused clarifying questions |
| Lawful in-scope request with insufficient evidence | safe/normal or high risk based on facts | `sources: []`; record evidence inadequacy | cautious no-source guidance/clarification or escalation; no strong claim |
| Supported low/medium-risk legal navigation | safe | selected approved evidence only | cautious guidance or clarification according to fact sufficiency |
| Unsupported topic or frozen unsupported language | product scope, not an API failure | no sources | normal HTTP 200 structured `unsupported` response |

## Wording-only generator contract

### Gate A

Gate A's generator is deterministic. It consumes the backend-owned `AnswerPlan` and produces deterministic rendered points/response-section wording. Important legal checklists, refusal, escalation, no-source caveats, and safety redirection remain deterministic plan content.

The generator must not decide which retrieval IDs become sources. The backend selects evidence and binds source IDs to `GuidancePoint` values before rendering. The current `GeneratedContent.used_source_ids` field is therefore a compatibility/migration concern, not the target authority design.

### Later LLM gate

If Gate F introduces an LLM, its maximum result is wording associated with allowed plan point IDs, conceptually:

```text
RenderedPoint { point_id, text }
```

The structural rules in ADR-004 apply: no unknown/duplicate IDs, required points remain, strength cannot increase, and final order follows the plan. The model cannot output or override:

- domain, risk, or decision;
- confidence;
- source IDs or source objects;
- safety notice;
- request/chat/message IDs;
- metadata/version stamps;
- new checklist/advice points; or
- final section order.

Unexpected fields are rejected, not trusted and overwritten silently. Deterministic rendering remains the fallback.

## Guard authority

Guards are veto/correction boundaries, not the normal decision policy.

- The schema guard validates the internal render and final public shape.
- The evidence guard enforces plan-point and selected-evidence containment. It does not certify legal correctness or semantic entailment.
- The output-safety guard scans local clauses so a refusal in one clause cannot excuse unsafe advice in a later clause.
- A guard may make content more cautious, raise risk/domain to `high_risk`, or change a permissive decision to escalation/refusal.
- A guard may never lower risk, remove a mandatory refusal/escalation, add unplanned advice, or invent evidence.
- Every override records stable reason codes and forces confidence recalculation from the post-guard result.

`SafetyPolicy` must not directly decide all legal responses merely because an output guard has final veto power. Safe low/medium navigation, missing facts, and no-source handling remain `ResponseDecisionPolicy` responsibilities.

## Backend-owned field invariants

| Field | Backend source | Forbidden source |
| --- | --- | --- |
| `domain` | routing + safety constraints + post-guard stricter override | renderer/LLM/frontend |
| `risk_level` | risk factors + safety policy + post-guard stricter override | missing facts alone, renderer/LLM |
| `decision` | `ResponseDecisionPolicy` + post-guard stricter override | detector shortcut, renderer/LLM/frontend |
| `confidence` | deterministic `ConfidenceCalculator` | model self-rating or legal-outcome probability |
| `sources` | selected `EvidenceBundle` mapped from the versioned corpus | generator-created IDs/objects or frontend |
| `safety_notice` | exact backend constant required by frozen contract | prompt/model/frontend rewrite |
| IDs | application/idempotent persistence | model, source corpus, frontend-generated response IDs |
| metadata | backend stages, guards, versions, adapter facts | raw provider output, prompts, secrets, hidden reasoning |

## Gate A boundary

Gate A uses:

- deterministic current-turn safety policy;
- deterministic routing/risk factors;
- deterministic response decision policy;
- the existing 26-snippet lexical corpus path;
- deterministic evidence selection and `AnswerPlan`;
- deterministic rendering;
- deterministic guards and confidence calculation; and
- backend-only finalization.

Gate A uses no LLM classifier, LLM generator, embeddings, semantic NLI guard, model-based confidence, or frontend policy fallback. It is not required to fix all current reviewed safety/paraphrase blockers; Gate B owns coverage improvement. Gate A must preserve the authority boundary while reporting those failures exactly.

## Later gates

- **Gate B:** may expand/tune safety and high-risk policy coverage after reviewed regression cases. It cannot let a model decide intent or weaken the clause-boundary output guard.
- **Gate E:** may improve context/topic switching. Current-turn safety remains prior and authoritative.
- **Gate F:** may add an LLM wording renderer with allowed point IDs and deterministic fallback. Backend evidence and decision authority remain unchanged.
- **Later retrieval promotion:** may improve candidate recall under ADR-005; retrieval never acquires response-decision authority.

## Consequences and trade-offs

### Positive consequences

- Model/provider compromise cannot directly alter classification, sources, IDs, notice, confidence, or metadata.
- Harmful intent, serious legal risk, and lack of evidence have different, testable behavior.
- Final fields always reflect post-guard values.
- Gate A remains reproducible and later LLM work has a narrow replaceable boundary.
- Existing backend-owned response construction is preserved and clarified rather than discarded.

### Costs and limitations

- Deterministic policies require reviewed pattern/routing coverage and can miss paraphrases.
- Separating policies, plan, renderer, guards, confidence, and finalizer adds internal contracts.
- Wording-only LLM output is less flexible than asking a model to compose an answer freely.
- Structural evidence containment cannot prove legal correctness or semantic support.
- Confidence remains a calibrated operational signal, not legal certainty.

## Rejected alternatives

### Let an LLM classify domain/risk/decision

Rejected because it makes frozen behavioral fields prompt-dependent and non-reproducible, and creates no enforceable safety authority.

### Let `SafetyPolicy` choose every response

Rejected because harmful intent, high legal risk, missing facts, insufficient evidence, and supported guidance are different conditions. Overloading safety policy creates false refusals and hides normal decision semantics.

### Let the generator select `used_source_ids`

Rejected as the target design. A constrained subset is safer than arbitrary sources, but evidence selection still belongs to backend policy before the plan. A later model may echo point IDs only.

### Trust a prompt to preserve backend fields

Rejected because prompts are not an enforcement boundary. The model output schema excludes authoritative fields, and the finalizer constructs them independently.

### Let the frontend correct unsafe or missing backend fields

Rejected because different clients would diverge, persisted content could remain unsafe, and the frontend has neither corpus nor policy authority.

### Allow guards to downgrade for fluency

Rejected because a final guard is escalation/caution only. A fluent draft cannot make a harmful/high-risk result less strict.

### Treat confidence as legal correctness

Rejected because neither routing scores nor source identity establishes the applicable law or likely outcome.

## Unresolved owner decisions

| Item | Status | Required decision |
| --- | --- | --- |
| Gate B policy change for lawful sentences containing unsafe tokens, such as “không phải né phạt” | **OWNER_DECISION_REQUIRED** | Gate A preserves frozen semantics; decide separately whether intent-level rules may narrow the raw-token refusal policy. |
| Police-tactical requests allowed by frozen specs as refusal or escalation | **OWNER_DECISION_REQUIRED** | Select a single deterministic mapping or explicitly preserve a reason-coded policy branch. |
| Exact confidence inputs/calibration and metadata explanation | **OWNER_DECISION_REQUIRED** | Approve values/thresholds without presenting them as legal certainty. |
| Whether refusal/escalation responses should expose selected `safety_policy` sources or normally return none | **OWNER_DECISION_REQUIRED** | Both can be safe; source display must not present an internal policy as law. |
| Stable policy reason-code taxonomy for harmful intent versus victim/high-risk reports | **OWNER_DECISION_REQUIRED** | Review with owner/legal stakeholders to avoid conflating “threaten someone” with “being threatened.” |
| Future LLM provider/model and whether Gate F is pursued | **DEFERRED** | No Gate A dependency and no transfer of authority when selected. |
| Automated semantic entailment/legal correctness guard | **DEFERRED** | It is explicitly not claimed: structural containment is enforceable, while legal correctness still requires qualified review. |

## Review readiness

This ADR is ready for architecture and product/safety review. The backend-owned authority boundary is locked. The listed policy/calibration choices must be recorded before code relies on one interpretation, but none is a reason to add an LLM or weaken deterministic Gate A behavior.
