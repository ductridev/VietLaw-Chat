# VietLaw-Chat Evaluation Strategy

**Status:** active diagnostic strategy

**MVP gate status:** proposed and implemented as the reviewed `mvp` suite; it
does not supersede `docs/archive/evaluation_plan.md` without product-owner
approval.

**Owner:** QA / evaluation

**Depends on:** `docs/api_contract.md`, `docs/ai_core_spec.md`,
`docs/rag_spec.md`, `docs/safety_policy.md`

## 1. Three layers, three different decisions

### Evaluation platform capability

The repository retains the full black-box platform: declarative cases, normal
oracles, metamorphic generation, fault injection, differential comparison,
load/stress measurement, optional LLM review, human-review routing, and all
reporters. Keeping a capability does not automatically make it a release gate.

### MVP release gate

The automated MVP gate is the explicit, reviewed `mvp` suite plus frozen legacy
compatibility and a fixed manual demo sample. At seed 20260713 the suite has
exactly **68 executions**: 44 curated cases and 24 reviewed, gate-eligible,
normalized-question-unique metamorphic cases.

The MVP decision must also run:

```bash
python3 scripts/run_eval.py --base-url <backend>  # 31 legacy case objects
python3 -m evaluation.cli run --base-url <backend> --suite mvp --seed 20260713
```

A backend is not accepted when this gate finds a genuine contract, session,
source, unsafe-refusal, or high-risk-escalation blocker. The reference
`backend_lite` is not automatically entitled to a green baseline.

### Post-MVP/nightly capability

`pr`, `full`, `nightly`, `release`, differential, load, stress, the complete
human-review queue, and the optional LLM judge remain available as diagnostic
or experimental capabilities. They are non-blocking until their own readiness
criteria and product-owner promotion are recorded.

## 2. What automation can establish

Automation can test:

- documented API shape and status behavior;
- session-ID ownership boundaries modeled by the MVP contract;
- persistence and reload equivalence;
- source identity against `data/legal_snippets.json`;
- a minimum excerpt-usefulness heuristic;
- unsafe refusal, high-risk escalation, and generated-output safety patterns;
- reviewed Vietnamese/no-diacritics/paraphrase behavior.

Automation cannot establish that legal guidance is correct or that a real
source supports the advice. Source identity is verified; excerpt usefulness is
heuristic; legal support remains **NOT VERIFIED** and requires a qualified
reviewer.

## 3. Oracle principles

1. Evaluation never imports backend business logic. Product backends are
   observed over HTTP.
2. Exact free-text answers are not golden strings. Classification, source
   identity, invariants, and forbidden behavior are pinned.
3. A blocker cannot be rescued by aggregate pass rate.
4. Input unsafe classification never uses the generated-output refusal
   exemption.
5. Generated output is segmented into local clauses. A refusal in one clause
   cannot excuse actionable advice in another.
6. A corpus match proves identity, not legal correctness.
7. Negative controls are required whenever an oracle changes.

## 4. Suite inventory and governance

Counts below are exact for seed 20260713 and the current configuration.

| Suite | Executions | Role | Default blocking use |
|---|---:|---|---|
| `smoke` | 19 | Fast backend_lite confidence check | PR/push |
| `mvp` | 68 | Reviewed MVP acceptance selection | Enable after its baseline is intentionally accepted |
| `pr` | 137 | Broad curated diagnostic | No |
| `metamorphic` | 214 | Generated-only diagnostic | No |
| `full` | 425 | 211 curated + 214 generated | No; nightly/manual diagnostic |
| `nightly` | 477 | 211 curated + 266 generated | No; scheduled diagnostic |
| `release` | 425 | Post-MVP full selection | No automatic MVP release authority |

The workflow always runs evaluator self-tests and backend_lite smoke on PRs.
The `mvp` job is guarded by repository variable `ENABLE_MVP_GATE=true`; this
must not be set until the team deliberately accepts a green target baseline.
Full/nightly/load run only scheduled or manually and are `continue-on-error`.

## 5. Metamorphic review policy

The generator still emits all 214 case IDs at seed 20260713. They contain 192
exact question strings and 75 normalized question keys; unique IDs are not
treated as unique semantic coverage.

`evaluation/config/metamorphic_review.yaml` records one of:

- `reviewed` + `gate_eligible: true`: may enter `mvp`;
- `unreviewed`: diagnostic only;
- `quarantined`: known malformed or meaning/fact-changing; diagnostic only.

Current registry: 30 reviewed/gate-eligible, 17 quarantined, 167 unreviewed.
At the mandatory review seed, six reviewed variants normalize to questions
already exercised by curated cases, so the MVP selector skips them and runs 24
reviewed generated executions. It also deduplicates generated variants against
one another and against every curated turn. The reviewed suite requires seed
20260713; changing it is a configuration error until the new generated content
is reviewed. Full and nightly retain every generated case for investigation.

## 6. Differential status

**Experimental.** Differential now retains the candidate's complete normal
oracle run and combines those failures with classified raw divergences. It is
still a reference-assisted diagnostic, not a legal ground-truth gate.

Promotion requires saved, reproducible candidate fixtures and demonstrated
handling of candidate-only source/safety/contract failures, reference failures,
safer candidates, and wording-only differences. No exact regression count may
be claimed without naming and preserving the scenario that produced it.

## 7. Load and stress status

**Nightly/manual measurement.** The MVP profile explicitly runs 100
different-chat requests and 20 same-chat requests at concurrency 5. Error rate
includes transport failures, timeouts, unexpected 4xx/5xx, and invalid JSON.
The command fails above 1% error or timeout rate.

Local backend throughput is not a production capacity claim. Stress remains
manual/nightly and never runs on PRs.

## 8. Human review

The complete auto-generated queue is retained for beta/post-MVP analysis. MVP
release does **not** require clearing it in full and the current code does not
claim to enforce such clearance.

The fixed MVP manual sample is ten responses:

1. civil deposit demo;
2. traffic record demo;
3. household-food-business demo;
4. same-chat deposit follow-up;
5. unsafe traffic evasion;
6. evidence destruction/hiding;
7. police summons/high-risk escalation;
8. deposit citation/source answer;
9. traffic citation/source answer;
10. business citation/source answer.

Review checks caution, factual fit, source usefulness, no guaranteed outcome,
and no actionable unsafe content. Legal correctness is not auto-certified.

## 9. Deferred capabilities

- Production differential gating until a production backend exists and saved
  candidate controls are maintained.
- Stress capacity conclusions until production deployment characteristics are
  available.
- Optional LLM judge as a gate; it remains off and may only add review signals.
- Full 214-variant blocking semantics until variants are individually reviewed.
- Complete human-review queue clearance as a release condition.
- Administrative/legal areas with no curated snippets.

## 10. Frozen-plan relationship

`docs/archive/evaluation_plan.md` remains the approved MVP support document
unless a product owner explicitly promotes this strategy. This document adds a
corrected diagnostic platform and a right-sized gate; its `active diagnostic`
status is not evidence of product-policy supersession.
