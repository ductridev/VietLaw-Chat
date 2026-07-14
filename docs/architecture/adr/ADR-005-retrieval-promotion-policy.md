# ADR-005: Retrieval Promotion Policy

- **Status:** PROPOSED — planning-only; owner review required before implementation
- **Scope:** Gate A lexical retrieval and any later hybrid-retrieval promotion
- **Depends on:** `docs/rag_spec.md`, `docs/api_contract.md`, `docs/evaluation_strategy.md`, `evaluation/config/legal_coverage.yaml`
- **Supersedes:** nothing

## Decision markers

- **DECIDED:** locked by the approved architecture prompt or frozen MVP specifications.
- **PROPOSED:** a reviewable implementation/measurement direction.
- **OWNER_DECISION_REQUIRED:** approval is needed before promotion or coding that depends on it.
- **DEFERRED:** outside Gate A.

## Context and problem

The current legal corpus contains 26 curated snippets. `backend_lite` currently performs deterministic, topic-gated lexical retrieval, while the frozen RAG specification explicitly recommends in-memory search before vector infrastructure. The small corpus and reviewed MVP gate favor inspectability, but lexical retrieval can eventually miss legitimate paraphrases.

Adding embeddings pre-emptively would introduce model/version dependencies, an index lifecycle, new failure modes, and a harder-to-explain ranking path before there is benchmark evidence that lexical recall is the limiting factor. Conversely, declaring lexical retrieval permanently sufficient would ignore measurable future gaps.

This ADR defines a promotion policy: Gate A stays lexical, and a later hybrid retriever earns promotion only against a reviewed benchmark.

## Decision

**DECIDED:** Gate A retrieval is the bounded pipeline:

```text
Vietnamese normalization
  -> lexical retrieval
  -> metadata/topic boost
  -> deduplication
  -> threshold
```

This order has the following precise meaning:

1. **Vietnamese normalization** preserves the original question and builds deterministic lowercase, punctuation/space-normalized, and accent-insensitive matching forms. Vietnamese `đ` and no-diacritics input must remain retrievable.
2. **Lexical retrieval** computes content relevance from the current question plus Gate A's bounded context terms. It uses approved corpus fields such as tags, title, plain-language summary, text, and source name.
3. **Metadata/topic boost** reranks candidates that have lexical content evidence. Domain, topic, source type, and status metadata may improve rank; a boost cannot make a content-irrelevant snippet eligible by itself.
4. **Deduplication** collapses repeated candidates by stable snippet ID before top-k and final selection. One approved source ID appears at most once.
5. **Threshold** removes candidates below the reviewed content-relevance threshold. If none survive, the correct result is `sources: []`, not a same-domain filler source.

The final retrieval result remains deterministic for the same accepted input, bounded context, corpus version, retriever version, and configuration.

## Gate A boundary

**DECIDED:** Gate A uses the existing 26 snippets and deterministic lexical retrieval. It does not include:

- embeddings or an embedding provider;
- vector storage or vector-index migration;
- hybrid lexical/vector fusion;
- semantic reranking by an LLM;
- an LLM classifier;
- web search, crawling, or runtime Markdown parsing;
- corpus expansion; or
- a fallback that returns an unrelated snippet merely to populate the source panel.

The retriever returns candidates and evidence metadata; it does not decide legal correctness, final safety, response wording, or API source objects. Selected source objects still come from the approved corpus and pass through the evidence/response boundary described by ADR-004.

### Gate A eligibility rules

Gate A must preserve these rules from the frozen RAG contract:

- deprecated snippets are excluded before scoring;
- content relevance is separate from ranking boosts;
- a domain/status/source-type boost alone is insufficient;
- same-chat context never comes from another `chat_id`;
- unsafe/high-risk requests may use only appropriate safety/high-risk evidence;
- top-k is bounded by configuration;
- healthy retrieval with no relevant result is HTTP success with `sources: []` and cautious output;
- an unreadable or invalid source store is an infrastructure failure, not a no-source result; and
- source identity/usefulness checks do not certify legal support.

**PROPOSED:** Gate A records, at minimum, `corpus_version`, `retriever_version`, normalized query diagnostics safe for in-memory trace, selected source IDs, and a no-source reason category. Full user text is not logged by default.

## Reviewed benchmark requirement

**DECIDED:** Embeddings or hybrid retrieval may be promoted only when a reviewed benchmark demonstrates that lexical retrieval lacks recall. A few hand-picked examples or an increased snippet count are not sufficient.

The benchmark must be:

- versioned and reproducible;
- reviewed for query meaning and expected relevant source IDs;
- separated into development and held-out evaluation sets, or otherwise protected from tuning leakage;
- representative of Vietnamese with and without diacritics, lawful paraphrases, follow-ups using bounded context, no-source questions, unsafe/high-risk requests, and cross-domain negatives;
- run against the same corpus snapshot and the same candidate eligibility rules; and
- accompanied by failure examples showing which relevant source lexical retrieval missed.

The lexical implementation is the baseline. A proposed hybrid retriever is evaluated side by side, not against an anecdotal target.

## Required promotion metrics

At minimum, every retrieval benchmark report includes:

| Metric | Definition for this decision | Why it matters |
|---|---|---|
| `Recall@5` | Share of benchmark queries for which at least one reviewed relevant source is in the top five | Detects missed relevant evidence |
| `MRR` | Mean reciprocal rank of the first reviewed relevant source | Rewards early useful evidence |
| `Precision@3` | Relevant returned sources divided by up to three returned sources | Prevents recall gains from flooding results |
| Wrong-domain rate | Share of returned sources outside the reviewed allowed domain/topic set | Detects unsafe or misleading cross-domain retrieval |
| No-source false-positive rate | Share of reviewed no-source queries that receive any source | Protects honest no-source behavior |
| Evidence adequacy rate | Share of reviewed queries whose selected evidence bundle is judged sufficient for the bounded planned guidance | Measures usefulness beyond ID/topic presence; requires human review |

Metric reports must include numerators, denominators, confidence/uncertainty appropriate to sample size, the benchmark/corpus/retriever versions, and the list of regressed cases. Aggregate averages must not hide a blocker such as a fabricated source, unsafe-source selection, or severe wrong-domain result.

**DECIDED:** Snippet count is not a corpus-quality KPI. It is inventory metadata only. More snippets can increase duplicates, stale law, contradictions, or irrelevant retrieval. Corpus quality requires reviewed coverage, provenance, freshness, topical relevance, and evidence adequacy.

## Later promotion gate

**DEFERRED:** Hybrid retrieval is a later-gate capability. It is not silently enabled by adding an embedding client or index.

Promotion requires all of the following:

1. the reviewed benchmark identifies material lexical recall misses;
2. the hybrid candidate improves `Recall@5` and/or `MRR` on those misses;
3. it does not cause an owner-unaccepted regression in `Precision@3`, wrong-domain rate, no-source false-positive rate, or evidence adequacy;
4. source identity, deprecated exclusion, safety-source restrictions, top-k, and no-source behavior remain intact;
5. embedding model, preprocessing, index build, corpus version, fusion rule, thresholds, and fallback mode are version-stamped;
6. deterministic lexical fallback behavior is defined and tested for provider/index failure;
7. operational cost, startup behavior, data handling, and rollback are reviewed; and
8. the product owner explicitly promotes the retriever version and the gate that may use it.

**OWNER_DECISION_REQUIRED:** Numeric promotion thresholds and the name/timing of the later gate are not approved by the current prompt. The owner must approve them after seeing the baseline distribution and benchmark size. This ADR must not fabricate those thresholds.

### Controlled comparison rules

**PROPOSED:** During a promotion experiment:

- keep the corpus and expected relevance labels fixed while comparing algorithms;
- report lexical-only and hybrid results separately;
- avoid changing safety policy, corpus content, thresholds, and retrieval algorithm in one un-attributable experiment;
- preserve case-level output for review;
- route substantive legal evidence adequacy to a qualified reviewer; and
- keep the hybrid path diagnostic/non-blocking until promotion is recorded.

## Consequences and trade-offs

### Positive consequences

- Gate A remains small, deterministic, inspectable, and easy to rollback.
- Retrieval failures can be attributed to normalization, lexical coverage, metadata boosts, or thresholds without an opaque embedding layer.
- Honest no-source behavior is protected.
- Later hybrid work receives a measurable entry criterion instead of being roadmap-driven infrastructure.
- Backend implementations can use independent algorithms while being measured against the same reviewed corpus/benchmark contract.

### Costs and limitations

- Lexical retrieval will miss some synonyms and paraphrases until the benchmark justifies promotion.
- Building and reviewing a useful benchmark takes product/legal effort.
- Evidence adequacy cannot be fully automated.
- Deterministic topic dictionaries and normalization rules require maintenance.
- The hybrid candidate may improve recall while adding cost, latency, and reproducibility risk; promotion is therefore a multi-metric decision, not a single-score win.

## Rejected alternatives

1. **Add embeddings in Gate A because they are standard RAG infrastructure.** Rejected because Gate A has no benchmark evidence that they solve its limiting problem and explicitly excludes them.
2. **Replace lexical retrieval with vector-only search.** Rejected because it weakens deterministic exact-term behavior and introduces an unnecessary hard dependency.
3. **Promote on Recall@5 alone.** Rejected because a system can increase recall by returning wrong-domain or no-source false positives.
4. **Use snippet count as the quality target.** Rejected because inventory size does not measure provenance, relevance, freshness, or legal adequacy.
5. **Allow metadata/domain boosts to create relevance.** Rejected because this returns unrelated same-domain sources.
6. **Use the LLM to choose sources directly.** Rejected because source selection and identity are backend responsibilities.
7. **Tune on the MVP gate and report the same cases as independent proof.** Rejected because it hides overfitting and does not demonstrate generalization.

## Owner decisions and deferred work

| Item | Marker | Required outcome |
|---|---|---|
| Gate A lexical pipeline | DECIDED | Implement normalization, lexical relevance, boosts, dedupe, and threshold only |
| Embeddings/hybrid in Gate A | DECIDED | Prohibited |
| Required six metrics | DECIDED | Report all for any promotion proposal |
| Snippet count as quality KPI | DECIDED | Prohibited |
| Benchmark composition/review owners | OWNER_DECISION_REQUIRED | Assign product/data/legal reviewers before a promotion study |
| Numeric promotion thresholds | OWNER_DECISION_REQUIRED | Set after baseline evidence; do not infer here |
| Later gate name and blocking status | OWNER_DECISION_REQUIRED | Record explicit product-owner promotion |
| Hybrid retriever implementation | DEFERRED | Only after reviewed evidence and approval |
| Corpus expansion | DEFERRED | Not part of Gate A |

## Compliance note

This ADR defines a promotion policy only. It does not add an embedding dependency, build an index, change corpus data, change thresholds, or implement retrieval code/tests.
