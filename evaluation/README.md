# VietLaw-Chat Evaluation Platform

A black-box HTTP evaluator for VietLaw-Chat. Normal suites never import
`backend/` or `backend_lite/`; load and fault infrastructure also use HTTP
directly. Reference and candidate backends receive the same case/oracle logic.

## What a green result means

The selected suite found no modeled blocker or blocking-threshold failure. The
platform can verify contract shape, MVP session ownership, persistence/reload,
corpus source identity, a minimum excerpt-usefulness heuristic, and modeled
safety behavior.

It **cannot** prove legal correctness or that a cited source supports the
guidance. Identity is verified, usefulness is heuristic, and legal support is
**NOT VERIFIED**. Substantive answers still require qualified human review.

## Install and self-test

```bash
python3 -m pip install -r evaluation/requirements.txt
python3 -m evaluation.cli validate
python3 -m pytest evaluation/tests -q
python3 -m evaluation.cli faults
```

Python 3.11+.

## Run the reviewed MVP gate

```bash
BACKEND_MODE=lite \
CHAT_DB_PATH=/tmp/vietlaw_eval.sqlite3 \
LEGAL_SNIPPETS_PATH="$PWD/data/legal_snippets.json" \
UNSAFE_PATTERNS_PATH="$PWD/data/unsafe_patterns.json" \
python3 -m uvicorn backend_lite.app.main:app --host 127.0.0.1 --port 8010

python3 -m evaluation.cli run \
  --base-url http://127.0.0.1:8010 --suite mvp --seed 20260713
```

At seed 20260713, `mvp` is exactly 68 executions: 44 curated and 24
human-reviewed, gate-eligible metamorphic variants. The normalized generated
questions are deduplicated against one another and every curated turn. The seed
is mandatory because changing it can change generated text under the same case
ID; a different seed requires re-review. A backend failing genuine
safety/high-risk cases is correctly rejected; the goal is not to make
`backend_lite` green.

## Suites

| Suite | Exact count at seed 20260713 | Role |
|---|---:|---|
| `smoke` | 19 | Required fast PR/push confidence check. |
| `mvp` | 68 | Reviewed MVP acceptance selection. |
| `pr` | 137 | Broad curated diagnostic. |
| `metamorphic` | 214 | Generated-only diagnostic. |
| `full` | 425 | All 211 curated + 214 generated; nightly/manual diagnostic. |
| `nightly` | 477 | More generated variants; scheduled diagnostic. |
| `release` | 425 | Post-MVP diagnostic selection, not an automatic queue-clear gate. |

Focused suites remain available: `contract`, `semantic`, `rag`, `safety`,
`conversation`, `language`, and `robustness`.

`evaluation/config/metamorphic_review.yaml` governs generated cases. Unreviewed
and quarantined variants remain visible in full/nightly output but cannot enter
the MVP gate. The registry contains 30 reviewed entries; six normalized
duplicates of curated questions are skipped, leaving 24 generated executions
in `mvp`. No variant is deleted.

## Differential (experimental)

```bash
python3 -m evaluation.cli differential \
  --reference-url http://127.0.0.1:8010 \
  --candidate-url http://127.0.0.1:8000 \
  --suite semantic
```

Differential retains and serializes both normal runs. Candidate contract,
source, or safety failures fail the combined result even when both sides share
the defect. Raw differences are classified as candidate regression, reference
limitation, acceptable wording, or human review. This is reference-assisted
diagnosis, not legal ground truth, and no exact regression-count claim is valid
without a saved scenario.

## Load (nightly/manual measurement)

```bash
python3 -m evaluation.cli load \
  --base-url http://127.0.0.1:8010 --profile mvp
```

The MVP profile explicitly runs 100 different-chat requests and 20 same-chat
requests at concurrency 5. Unexpected HTTP 4xx/5xx, invalid JSON, transport
errors, and timeouts contribute to error rate. More than 1% errors or timeouts
returns exit 1. Local throughput is not production capacity evidence; stress
never runs on PRs.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | Selected gate/measurement passed |
| 1 | Evaluation or configured load threshold failed |
| 2 | Configuration/schema/selection error |
| 3 | Backend unavailable |

## Architecture

```text
cases/*.yaml          declarative cases
  -> runners/         session/chat discipline and execution
    -> clients/       normal suite HTTP transport
      -> oracles/     contract, semantic, source, safety, conversation
        -> metrics/thresholds
          -> console, JSON, Markdown, JUnit, HTML reporters

load_runner/fault_proxy also perform direct black-box HTTP for their own roles.
```

One blocker cannot be outvoted by aggregate pass rate. `RunResult.ok` enforces
that decision and unit tests pin it.

## Adding cases and generated reviews

Cases must cite requirement IDs, use accepted sets rather than exact full
answers, and declare per-turn safety semantics in multi-turn cases. Contradictory
source rules, invalid source counts, first-turn chat reuse, attacker operations
without targets, and cross-session reuse are schema errors.

New generated variants default to `unreviewed`/diagnostic-only. Promote one to
the MVP gate only after checking that actor, victim, negation, timeline, and
material facts did not change; record that decision in
`config/metamorphic_review.yaml`.

## Governance

See `docs/evaluation_strategy.md`. The full platform is preserved, but keeping
a capability does not promote it to a mandatory MVP gate. The complete human
review queue, differential gating, stress, and the optional LLM judge remain
post-MVP/experimental until explicitly promoted.
