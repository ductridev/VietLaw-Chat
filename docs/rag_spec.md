# VietLaw-Chat RAG Specification — MVP v1

**Status:** MVP v1 frozen draft  
**Owner:** AI Core / RAG owner  
**Depends on:** `docs/api_contract.md`, `docs/ai_core_spec.md`, `data/legal_snippets.json`, `data/unsafe_patterns.json`  
**Review rule:** after this version is accepted, any change that affects source object shape, retrieval behavior, citation safety, no-source behavior, or evaluation expectations must be approved by both product/frontend owner and backend/AI-core owner.

---

## 1. Purpose

This document defines the Retrieval-Augmented Generation specification for **VietLaw-Chat MVP v1**.

The RAG layer provides a small, controlled, source-grounded retrieval system for Vietnamese legal navigation questions.

The goal is **not** to build a complete Vietnamese legal search engine.

The goal is to support the MVP demo by helping AI Core:

- retrieve relevant legal/procedural snippets;
- provide source candidates to the prompt builder;
- reduce hallucination;
- avoid fabricated legal citations;
- support the 3 main demo domains;
- support unsafe/high-risk refusal or escalation;
- return source objects compatible with `docs/api_contract.md`;
- support deterministic evaluation.

---

## 2. MVP Scope

### 2.1. In scope

RAG MVP supports:

- loading `data/legal_snippets.json`;
- validating snippet schema at startup;
- excluding deprecated snippets;
- retrieving sources by domain, tags, title, summary, and text;
- accent-insensitive matching for Vietnamese without diacritics;
- retrieving top 1–3 relevant sources;
- providing retrieved source ids to the LLM prompt as `allowed_source_ids`;
- allowing the LLM to output only `used_source_ids`;
- mapping valid `used_source_ids` to full source objects in Response Builder;
- returning `sources: []` when no relevant source exists;
- making no-source responses cautious;
- supporting golden case evaluation;
- supporting same-chat follow-up through AI Core context.

### 2.2. Out of scope

RAG MVP does **not** include:

- crawling a full legal database;
- web search;
- vector database as a required dependency;
- legal document upload;
- OCR;
- voice retrieval;
- bilingual retrieval;
- full statute parsing;
- auto-updating legal sources;
- user-specific long-term memory;
- cross-chat retrieval;
- external source ingestion from frontend;
- letting the LLM create final source objects.

---

## 3. Source of Truth

The following files are source of truth for RAG implementation:

| File | Role |
|---|---|
| `docs/api_contract.md` | Final API response shape, source object contract, error behavior |
| `docs/ai_core_spec.md` | AI Core/RAG/LLM boundary, `used_source_ids`, citation guard, failure matrix |
| `docs/safety_policy.md` | Safety behavior and refusal/escalation rules |
| `data/legal_snippets.json` | Curated source pack used by RAG |
| `data/unsafe_patterns.json` | Deterministic unsafe/high-risk pattern data |
| `data/golden_cases.json` | Evaluation cases |
| `data/demo_cases.json` | Demo scenarios |

RAG must not silently change API response shape. If this document conflicts with `api_contract.md`, the API contract wins.

---

## 4. RAG Role in the System

System flow:

```text
User message
→ API request validation
→ ChatStore loads same-chat history
→ Input normalization
→ Language detection
→ Unsafe intent detection
→ Legal domain classification
→ Risk classification
→ Decision policy
→ RAG retrieval
→ Prompt Builder receives retrieved sources + allowed_source_ids
→ LLM generates content-only JSON
→ Output Parser validates used_source_ids
→ Citation Guard checks used_source_ids
→ Safety Guard may escalate
→ Response Builder maps used_source_ids to final source objects
→ Store assistant message
→ API response
```

RAG is responsible for **retrieving source candidates**.

RAG is **not** responsible for:

- final domain classification;
- final risk classification;
- final decision policy;
- final safety refusal/escalation;
- final API response construction;
- chat storage;
- source object invention;
- legal judgment.

---

## 5. Key Architecture Rules

1. RAG returns source candidates from approved files only.
2. RAG never invents sources, URLs, law names, article numbers, agency names, or legal text.
3. LLM never creates final `sources` objects.
4. LLM may only output `used_source_ids` from the allowed retrieved source ids.
5. Response Builder maps `used_source_ids` to final API source objects.
6. Citation Guard verifies `used_source_ids ⊆ retrieved_source_ids`.
7. Deprecated snippets must never be returned.
8. No-source retrieval is not an error.
9. Broken source store is an error.
10. RAG must be deterministic enough for golden case evaluation.

---

## 6. Runtime Data File and Authoring Workflow

### 6.1. Runtime source of truth

RAG runtime must load only:

```text
data/legal_snippets.json
```

This JSON file is the runtime contract for RAG, AI Core, API response building, and evaluation.

Runtime code must not read Markdown files directly.

The file is owned by the product/data/evaluation owner.

The RAG owner may read this file but must not change its schema without approval.

### 6.2. Authoring workflow

The team may author legal snippets in Markdown for readability, but Markdown is only an authoring format.

Required MVP workflow:

```text
data/snippets_md/*.md
→ scripts/build_snippets.py
→ data/legal_snippets.json
→ RAG runtime loads JSON only
```

Rules:

1. `data/legal_snippets.json` remains the only runtime source of truth.
2. Commit both the source Markdown files and the generated JSON file.
3. Teammate backend code, eval scripts, and RAG runtime must not require running the Markdown compiler.
4. The compiler is one-way: Markdown → JSON. Do not build a two-way sync system in MVP.
5. The compiler must validate required fields and fail with a clear file/field error.
6. Runtime startup validation must still validate `data/legal_snippets.json`; compile-time validation does not replace runtime validation.

Recommended compiler scope:

```text
scripts/build_snippets.py
- read data/snippets_md/*.md
- parse YAML-style frontmatter
- parse H1 as title
- parse ## Text as text
- parse ## Plain summary as plain_language_summary
- validate schema
- write data/legal_snippets.json
```

Do not add watch mode, incremental builds, database export, or CI-only generation for MVP v1.

### 6.3. Markdown snippet format

Recommended authoring format:

```markdown
---
id: civil_deposit_001
domain: civil_dispute
source_name: "Bộ luật Dân sự 2015 - Điều 328"
source_url: https://example.gov.vn/source
source_type: official_source
status: active
tags: [dat_coc, tien_coc, hop_dong]
risk_notes: [medium_risk, money_dispute]
last_checked: 2026-07-10
---
# Đặt cọc để bảo đảm giao kết hoặc thực hiện hợp đồng

## Text
Đặt cọc là việc một bên giao cho bên kia...

## Plain summary
Nếu bị giữ tiền cọc, người dùng cần kiểm tra thỏa thuận đặt cọc, hợp đồng và chứng từ thanh toán.
```

Mapping rules:

| Markdown part | JSON field |
|---|---|
| frontmatter `id` | `id` |
| frontmatter `domain` | `domain` |
| frontmatter `source_name` | `source_name` |
| frontmatter `source_url` | `source_url` |
| frontmatter `source_type` | `source_type` |
| frontmatter `status` | `status` |
| frontmatter `tags` | `tags` |
| frontmatter `risk_notes` | `risk_notes` |
| frontmatter `last_checked` | `last_checked` |
| H1 | `title` |
| `## Text` | `text` |
| `## Plain summary` | `plain_language_summary` |

### 6.4. Markdown/JSON drift risk

The trade-off of Markdown authoring is that Markdown and generated JSON can drift if someone edits one but not the other.

MVP rule:

```text
All data edits should go through Markdown, then rebuild data/legal_snippets.json.
```

The generated JSON may include a top-level or metadata note such as:

```json
{
  "_generated_from": "data/snippets_md/",
  "_do_not_edit_manually": true,
  "snippets": []
}
```

However, if the runtime schema expects a plain list, keep the generated JSON as a plain list for MVP and place the warning in `data/snippets_md/README.md` instead. Do not break the runtime schema just to add metadata.

## 7. Legal Snippet Schema

Each item in `data/legal_snippets.json` must follow this schema:

```json
{
  "id": "civil_deposit_001",
  "domain": "civil_dispute",
  "title": "Đặt cọc để bảo đảm giao kết hoặc thực hiện hợp đồng",
  "source_name": "Bộ luật Dân sự 2015 - Điều 328",
  "source_url": "https://example.gov.vn/source",
  "source_type": "official_source",
  "status": "active",
  "text": "Short relevant snippet used for retrieval and grounding.",
  "plain_language_summary": "Short explanation in simple Vietnamese.",
  "tags": ["dat_coc", "tien_coc", "hop_dong"],
  "risk_notes": ["medium_risk", "money_dispute"],
  "last_checked": "2026-07-10"
}
```

---

## 8. Required Snippet Fields

| Field | Required | Rule |
|---|---:|---|
| `id` | yes | Unique stable id. Must not change once referenced by tests or demo cases. |
| `domain` | yes | Must be one of supported MVP domains. |
| `title` | yes | Human-readable source/snippet title. |
| `source_name` | yes | Name of legal/procedural/internal source. |
| `source_url` | no | Can be empty for internal safety notes. Must never be invented. |
| `source_type` | yes | Must be one of allowed source types. |
| `status` | yes | `active`, `needs_review`, `demo_only`, or `deprecated`. |
| `text` | yes | Main text used for retrieval and prompt grounding. |
| `plain_language_summary` | recommended | Plain Vietnamese explanation. |
| `tags` | yes | Retrieval tags. |
| `risk_notes` | recommended | Risk/safety hints. |
| `last_checked` | yes | Source review date in `YYYY-MM-DD`. |

Startup validation should fail with `retrieval_error` if required fields are missing or if the JSON file is corrupt.

---

## 9. Supported Domains

RAG must support the same domain values as the API contract:

| Domain | Meaning |
|---|---|
| `civil_dispute` | Deposit, rental, loan, simple contract, consumer dispute |
| `traffic` | Traffic fine, traffic violation record, traffic document checklist |
| `household_business` | Household business, small shop, selling food online |
| `administrative` | General administrative/procedure issue |
| `high_risk` | Criminal/police/serious issue, unsafe intent, escalation snippets |
| `unknown` | Unknown or unsupported topic |

If a user question contains unsafe or serious high-risk signals, AI Core should classify domain as `high_risk`. RAG should then prefer high-risk/safety snippets.

Example:

```text
Làm sao để né phạt giao thông?
```

Expected classification before RAG:

```json
{
  "domain": "high_risk",
  "risk_level": "high",
  "decision": "refuse_unsafe_request",
  "detected_topic": "traffic"
}
```

RAG may use `detected_topic` to find relevant safety snippets, but final domain remains `high_risk`.

---

## 10. Source Types

Allowed `source_type` values:

| Source type | Meaning | Use in MVP |
|---|---|---|
| `official_source` | Official legal/government source | Preferred for legal grounding |
| `procedure` | Public service or administrative procedure source | Preferred for procedure/checklist guidance |
| `legal_snippet` | Curated legal excerpt with reviewed source | Acceptable if reviewed |
| `curated_note` | Internal reviewed note/checklist based on product review | Use cautiously; do not overstate as official law |
| `safety_policy` | Internal safety/refusal/escalation rule | Use for refusal/escalation support, not legal authority |
| `demo_only` | Demo-only controlled source | Avoid for strong claims |

Rules:

- Prefer `official_source` and `procedure` when available.
- `curated_note` is acceptable for checklist guidance, but should not be described as official legal authority.
- `safety_policy` can support refusal/escalation behavior.
- `demo_only` must be lower priority than active official/procedure sources.
- Deprecated snippets must never be returned.

---

## 11. Snippet Status Handling

Allowed `status` values:

| Status | Can return? | Rule |
|---|---:|---|
| `active` | yes | Reviewed and usable. |
| `needs_review` | limited | Can be used only if no stronger source exists; answer must be cautious. |
| `demo_only` | limited | Demo-only; do not use for strong legal claims. |
| `deprecated` | no | Must be excluded before scoring. |

Retrieval priority:

```text
active > needs_review > demo_only
```

Hard rule:

```text
status == deprecated → exclude before scoring.
```

Implementation warning:

```text
`demo_only` can appear as both a `status` value and a `source_type` value. These fields have different meanings. Do not write filters that confuse source_type == demo_only with status == demo_only.
```

- `status == demo_only` means the snippet itself is limited-use demo data.
- `source_type == demo_only` means the source category is demo-only.
- `status == deprecated` is the only hard exclusion status besides corrupt/missing data.

---

## 12. API Source Object Contract

Final API `sources` must match `docs/api_contract.md`.

RAG returns internal retrieved source objects. Response Builder converts them into this API shape:

```json
{
  "id": "civil_deposit_001",
  "title": "Đặt cọc để bảo đảm giao kết hoặc thực hiện hợp đồng",
  "source_name": "Bộ luật Dân sự 2015 - Điều 328",
  "url": "https://example.gov.vn/source",
  "snippet": "Short relevant excerpt from the approved snippet.",
  "source_type": "official_source",
  "last_checked": "2026-07-10"
}
```

| API field | Source field | Required | Rule |
|---|---|---:|---|
| `id` | `id` | yes | Must match retrieved snippet id. |
| `title` | `title` | yes | Must come from approved snippet. |
| `source_name` | `source_name` | yes | Must come from approved snippet. |
| `url` | `source_url` | no | Can be empty/null. Must not be invented. |
| `snippet` | `text` or faithful excerpt of `text` | yes | Must be faithful to approved snippet. |
| `source_type` | `source_type` | yes | Must be allowed source type. |
| `last_checked` | `last_checked` | yes | Must come from approved snippet. |

Source object rules:

1. Do not invent ids.
2. Do not invent URLs.
3. Do not invent law names, article numbers, decree numbers, or agency names.
4. Do not cite sources not retrieved for the current request.
5. Do not return deprecated sources.
6. If no relevant source exists, return `sources: []`.
7. If source is weak, answer must be cautious.
8. If source is internal safety policy, do not present it as official law.

---

## 13. RAG Function Contract

Recommended internal function:

```python
retrieve_sources(
    question: str,
    normalized_question: str,
    domain: str,
    risk_level: str,
    decision: str,
    same_chat_context: dict | None = None,
    detected_topic: str | None = None,
    top_k: int = 3,
) -> RetrievalResult
```

### 13.1. Input fields

| Field | Required | Description |
|---|---:|---|
| `question` | yes | Latest user message in original form. |
| `normalized_question` | yes | Normalized/accent-insensitive form for matching. |
| `domain` | yes | Backend-predicted domain. |
| `risk_level` | yes | Backend-predicted risk level. |
| `decision` | yes | Backend decision hint. |
| `same_chat_context` | conditional | Same-chat context summary/facts from AI Core. Optional for first-turn retrieval; required for follow-up retrieval when the latest question lacks domain terms. |
| `detected_topic` | no | Topic such as `traffic` when final domain is `high_risk`. |
| `top_k` | no | Default 3. |

### 13.2. Output shape

```json
{
  "sources": [
    {
      "id": "civil_deposit_001",
      "title": "Đặt cọc để bảo đảm giao kết hoặc thực hiện hợp đồng",
      "source_name": "Bộ luật Dân sự 2015 - Điều 328",
      "source_url": "https://example.gov.vn/source",
      "source_type": "official_source",
      "status": "active",
      "text": "Short source text.",
      "plain_language_summary": "Plain summary.",
      "tags": ["dat_coc", "tien_coc"],
      "risk_notes": ["medium_risk"],
      "last_checked": "2026-07-10",
      "score": 8.5
    }
  ],
  "allowed_source_ids": ["civil_deposit_001"],
  "retrieval_count": 1,
  "has_sources": true,
  "retrieval_strategy": "in_memory_keyword_v1"
}
```

Rules:

- `allowed_source_ids` must exactly match returned retrieved source ids.
- `retrieval_count` is the number of sources returned after filtering.
- `has_sources` is `true` only if `retrieval_count > 0`.
- Scores are internal/debug only and should not be shown as legal certainty.
- Final API response may omit internal scores unless debug metadata later adds them.

---

## 14. LLM Boundary: `used_source_ids`

RAG provides retrieved sources and allowed source ids to Prompt Builder.

Prompt Builder passes:

```text
Retrieved sources:
{retrieved_sources}

Allowed retrieved source ids:
{allowed_source_ids}
```

LLM may output only:

```json
{
  "summary": "...",
  "clarifying_questions": [],
  "checklist": [],
  "next_steps": [],
  "used_source_ids": ["civil_deposit_001"]
}
```

LLM must not output:

- `sources` objects;
- `source_url`;
- `source_name`;
- article numbers not present in retrieved sources;
- legal citations not present in retrieved sources;
- `metadata`;
- `safety_notice`;
- `domain`;
- `risk_level`;
- `decision`.

Response Builder maps valid `used_source_ids` to final `sources` using the retrieved source map.

Citation Guard checks:

```text
used_source_ids ⊆ allowed_source_ids
```

Invalid ids must be removed.

---

## 15. Prompt Context Format

RAG should provide retrieved sources to Prompt Builder in a compact, explicit format.

Recommended format:

```text
Retrieved sources:

Source 1:
id: civil_deposit_001
title: Đặt cọc để bảo đảm giao kết hoặc thực hiện hợp đồng
source_name: Bộ luật Dân sự 2015 - Điều 328
source_type: official_source
status: active
last_checked: 2026-07-10
text: Đặt cọc là việc một bên giao cho bên kia...
plain_language_summary: Nếu bị giữ tiền cọc, người dùng cần kiểm tra...

Allowed retrieved source ids:
- civil_deposit_001
```

Prompt instruction:

```text
Use only these retrieved sources for legal/procedural claims.
If sources are insufficient, say source coverage is limited and avoid strong legal conclusions.
When using sources, output only their ids in used_source_ids.
Do not create source objects.
```

---

## 16. Input Normalization for Retrieval

RAG relies on `input_normalizer.py` and must support Vietnamese with and without diacritics.

Normalization should produce:

- original question;
- lowercase form;
- punctuation-normalized form;
- duplicate-space-normalized form;
- accent-insensitive form.

Example:

```text
Original:
Tôi thuê nhà, chủ nhà giữ tiền cọc 2 tháng không trả, tôi phải làm gì?

Normalized:
tôi thuê nhà chủ nhà giữ tiền cọc 2 tháng không trả tôi phải làm gì

Accent-insensitive:
toi thue nha chu nha giu tien coc 2 thang khong tra toi phai lam gi
```

Hard rule:

```text
Vietnamese without diacritics must still match Vietnamese legal snippets.
```

Examples that must retrieve relevant sources:

```text
toi thue nha chu nha giu tien coc khong tra
lam sao de ne phat giao thong
toi muon ban do an online o que can giay to gi
```

---

## 17. Recommended MVP Retrieval Strategy

Use a simple hybrid keyword strategy.

MVP retrieval should be easy to debug and deterministic.

### Step 1 — Load and validate source pack

- Load `data/legal_snippets.json` at startup.
- Validate required fields.
- Build normalized text fields for each snippet.
- Build tag index if useful.
- Exclude deprecated snippets before scoring.

If file is missing/corrupt/unreadable:

```text
retrieval_error HTTP 503
```

### Step 2 — Build retrieval query

RAG must build a **combined retrieval query** before scoring.

Use:

- latest user question;
- normalized question;
- accent-insensitive question;
- same-chat context summary/facts when the request is a follow-up;
- predicted domain;
- risk level;
- decision;
- detected topic if domain is `high_risk`.

Required combined query shape:

```text
combined_query = latest_question
               + normalized_question
               + accent_insensitive_question
               + known facts/topic terms from same-chat context
```

For first-turn requests, same-chat context may be empty.

For follow-up turns, same-chat context inclusion is mandatory when the latest question does not contain enough domain terms by itself.

Example:

```text
Turn 1: Tôi thuê nhà, chủ nhà giữ tiền cọc 2 tháng không trả...
Turn 2: Vậy tôi cần chuẩn bị giấy tờ gì?
```

For Turn 2, the latest question may not contain `tiền cọc`, `thuê nhà`, or `hợp đồng`. ContextBuilder must provide known topic/facts such as `thuê nhà`, `tiền cọc`, `chủ nhà giữ cọc`, and `hợp đồng thuê nhà` so RAG can still retrieve civil deposit/rental checklist snippets.

Content scoring must be computed against `combined_query`, not only the latest user question.

RAG must not retrieve from other chats.

### Step 3 — Content relevance gate

RAG scoring must separate **content relevance** from **ranking boosts**.

This is a hard rule for MVP because domain/status boosts alone can otherwise return unrelated sources from the same domain.

Use two score buckets computed against `combined_query`:

```text
content_score = tag_match_score(combined_query)
              + title_match_score(combined_query)
              + summary_match_score(combined_query)
              + text_match_score(combined_query)
              + source_name_match_score(combined_query)
boost_score   = domain_boost + status_boost + source_type_boost
total_score   = content_score + boost_score
```

Preliminary relevance gate:

```text
A snippet can be considered only if content_score >= 1.
```

Final candidate threshold:

```text
minimum_content_score = 2
A snippet can enter the final candidate set only if content_score >= minimum_content_score.
```

Recommended behavior:

- If `content_score < 1`, exclude the snippet immediately.
- If `content_score < minimum_content_score`, exclude the snippet for MVP v1.
- If no candidate reaches `minimum_content_score`, return `sources: []` unless there is a directly relevant safety source.
- Use `boost_score` only to rank candidates that already passed the content relevance gate.
- Never return a snippet only because it shares the same domain and has `status: active`.

Example bug this prevents:

```text
Question: Tôi thuê nhà, chủ nhà giữ tiền cọc không trả.
Unrelated snippet: vay tiền không trả.
Same domain: civil_dispute.
No tag/text/title match to deposit/rental.
Result: excluded because content_score = 0, even if domain/status boosts are high.
```

### Step 4 — Domain boost

Domain boost ranks already-relevant candidates. It must not decide relevance by itself.

Recommended boost scoring:

| Condition | Boost score |
|---|---:|
| snippet.domain == predicted domain | +3 |
| snippet.domain == detected_topic when final domain is `high_risk` | +1 |
| snippet.domain == `high_risk` for unsafe/high-risk decision | +3 |
| related administrative/procedure source | +1 |
| unrelated domain | -2 |

Do not hard-filter domain too aggressively in MVP. Keyword/tag match may still find useful procedure/safety snippets.

### Step 5 — Tag matching

Tag matching contributes to `content_score`.

Recommended scoring:

| Condition | Content score |
|---|---:|
| exact tag match | +3 |
| accent-insensitive tag match | +3 |
| partial tag match | +1 |
| synonym match | +2 |

Tag examples:

- `tien_coc`, `dat_coc`, `thue_nha`
- `phat_giao_thong`, `bien_ban`, `ne_phat`
- `ho_kinh_doanh`, `ban_do_an_online`, `an_toan_thuc_pham`
- `cong_an`, `high_risk`, `refuse_unsafe_request`

### Step 6 — Text/title/summary matching

Text/title/summary matching contributes to `content_score`.

Recommended scoring:

| Field | Content score |
|---|---:|
| title match | +2 |
| plain_language_summary match | +1.5 |
| text match | +1 |
| source_name match | +0.5 |

Use both Vietnamese and accent-insensitive matching.

### Step 6.5 — Status/source boost

Status/source scoring contributes to `boost_score`, not `content_score`.

Recommended boost scoring:

| Condition | Boost score |
|---|---:|
| status == active | +2 |
| status == needs_review | +0.5 |
| status == demo_only | -1 |
| source_type == official_source | +1 |
| source_type == procedure | +1 |
| source_type == safety_policy for unsafe/high-risk decision | +1 |
| status == deprecated | exclude |

MVP caution rule:

```text
If any returned source has status != active, Prompt Builder must instruct the LLM to use cautious wording and avoid strong legal claims.
```

### Step 7 — Return top K

MVP default:

```text
top_k = 3
```

Rules:

- Return top 1–3 relevant sources.
- Maximum for MVP should be 5.
- Prefer fewer relevant sources over many weak sources.
- Return empty sources if score is below threshold.

---

## 18. Retrieval Threshold

MVP retrieval uses a content-first threshold.

Recommended values:

```text
minimum_content_score = 2
max_results = 3
max_results_absolute = 5
```

Behavior:

- Candidate snippets must pass the content relevance gate before boosts are applied.
- `content_score` must be computed against `combined_query`, including same-chat context terms for follow-up turns.
- `boost_score` can change ranking, but cannot make an unrelated snippet relevant.
- If no candidate has enough content relevance, return `sources: []`.
- Weak candidates are excluded in MVP v1; do not keep a separate weak-candidate fallback path.
- Never return unrelated sources just to fill the source panel.

No-source is better than fake relevance.

Pseudo-code:

```python
combined_query = build_combined_query(
    latest_question=question,
    normalized_question=normalized_question,
    same_chat_context=same_chat_context,
    domain=domain,
    risk_level=risk_level,
    decision=decision,
    detected_topic=detected_topic,
)

for snippet in snippets:
    if snippet.status == "deprecated":
        continue

    content_score = score_tags(snippet, combined_query) + score_text_fields(snippet, combined_query)

    if content_score < minimum_content_score:
        continue

    boost_score = score_domain(snippet, domain, detected_topic) + score_status_and_type(snippet)
    total_score = content_score + boost_score
    candidates.append((snippet, content_score, boost_score, total_score))

return top_k_by_total_score(candidates)
```

## 19. Domain-specific Retrieval Requirements

### 19.1. Civil Dispute

Common keywords:

- tiền cọc
- dat coc / đặt cọc
- chủ nhà
- thuê nhà
- hợp đồng
- vay tiền
- nợ tiền
- không trả
- mua hàng online
- shop không giao
- chứng từ
- biên nhận
- timeline

Preferred tags:

- `dat_coc`
- `tien_coc`
- `hop_dong`
- `hop_dong_thue_nha`
- `vay_tien`
- `tranh_chap_tien`
- `chung_tu`
- `dan_su`

Expected sources:

- deposit/contract snippet;
- rental/deposit checklist snippet;
- loan/evidence snippet;
- consumer dispute snippet when applicable.

### 19.2. Traffic

Common keywords:

- phạt giao thông
- phat giao thong
- biên bản
- bien ban
- giấy phạt
- giay phat
- bằng lái
- vi phạm giao thông
- lỗi trong biên bản
- tai nạn giao thông

Preferred tags:

- `giao_thong`
- `bien_ban`
- `giay_phat`
- `vi_pham_giao_thong`
- `giay_to_xe`
- `khieu_nai`
- `tai_nan`

Expected sources:

- traffic law/procedure snippet;
- traffic document checklist snippet;
- traffic safety/high-risk snippet when unsafe intent appears.

Unsafe traffic queries such as `né phạt` / `ne phat` must be routed by AI Core as `high_risk` and retrieve safety/high-risk snippets only if useful.

### 19.3. Household Business

Common keywords:

- hộ kinh doanh
- ho kinh doanh
- bán đồ ăn online
- ban do an online
- mở quán nhỏ
- đăng ký kinh doanh
- giấy phép
- an toàn thực phẩm
- kinh doanh nhỏ
- bán hàng online

Preferred tags:

- `ho_kinh_doanh`
- `ban_do_an_online`
- `dang_ky_kinh_doanh`
- `an_toan_thuc_pham`
- `kinh_doanh_nho`
- `thu_tuc_hanh_chinh`

Expected sources:

- household business registration snippet;
- food safety snippet;
- local/procedure verification snippet;
- business safety snippet if user asks to bypass registration.

### 19.4. High-risk / Safety

Common keywords:

- công an
- cong an
- bị bắt
- bi bat
- bị điều tra
- bị tố cáo hình sự
- khai gì để không bị tội
- giấu chứng cứ
- giau chung cu
- xóa tin nhắn
- làm giả giấy tờ
- né phạt
- lách luật
- đe dọa
- tai nạn có người bị thương
- tranh chấp đất
- tiền tỷ / hàng trăm triệu

Preferred tags:

- `high_risk`
- `hinh_su`
- `cong_an`
- `luat_su`
- `refuse_unsafe_request`
- `requires_escalation`
- `evidence_hiding`
- `fake_documents`
- `ne_phat`
- `do_not_evade`

Expected sources:

- safety escalation snippet;
- professional-help recommendation snippet;
- safe preparation checklist snippet;
- refusal support snippet.

RAG must not retrieve sources that enable evasion or tactical criminal defense.

---

## 20. Unsafe Query Interaction

RAG is not the primary safety layer, but it must support safety behavior.

If unsafe intent is detected before retrieval:

- prefer high-risk/safety snippets;
- avoid normal how-to snippets that could help evasion;
- return safety/professional-help snippets if available;
- return `sources: []` if only harmful/irrelevant sources would match.

Unsafe examples:

```text
Làm sao để né phạt giao thông?
lam sao de ne phat giao thong
Tôi nên nói gì với công an để không bị tội?
Làm sao để giấu chứng cứ?
Làm sao để làm giả giấy tờ?
Tôi muốn lách giấy phép để bán hàng nhanh hơn.
```

Expected behavior after AI Core and RAG:

```json
{
  "domain": "high_risk",
  "risk_level": "high",
  "decision": "refuse_unsafe_request",
  "sources": []
}
```

or:

```json
{
  "domain": "high_risk",
  "risk_level": "high",
  "decision": "refuse_unsafe_request",
  "sources": ["safety/high-risk snippets only"]
}
```

No tactical instructions are allowed.

---

## 21. No-source Behavior

If RAG returns no relevant sources:

```json
{
  "sources": [],
  "allowed_source_ids": [],
  "retrieval_count": 0,
  "has_sources": false
}
```

No-source is not a backend error.

The final response must:

- avoid strong legal conclusions;
- ask clarifying questions if needed;
- say source coverage is limited when relevant;
- provide safe checklist/next steps only;
- recommend lawyer/authority for important or high-risk matters.

Allowed wording style:

```text
Hiện bản MVP chưa có nguồn phù hợp để đưa ra căn cứ cụ thể cho trường hợp này. Tôi có thể giúp bạn xác định thông tin cần chuẩn bị, nhưng bạn nên kiểm tra thêm với luật sư hoặc cơ quan chức năng trước khi hành động.
```

Not allowed:

```text
Theo luật, bạn chắc chắn có quyền yêu cầu bồi thường.
```

---

## 22. Citation Safety Rules

Citation safety is enforced by Output Parser, Citation Guard, and Response Builder, but RAG must provide clean inputs.

Rules:

1. Do not fabricate citations.
2. Do not fabricate URLs.
3. Do not fabricate law names, article numbers, decree numbers, dates, or agency names.
4. Do not return sources that were not retrieved for the current request.
5. Do not overstate what a source says.
6. Do not return deprecated sources.
7. If source is loosely related, answer must be cautious.
8. If source status is `needs_review` or `demo_only`, avoid strong claims.
9. If no source exists, return `sources: []`.
10. LLM may only refer to sources via `used_source_ids`.

---

## 23. RAG Metadata

RAG should provide metadata used by AI Core response metadata.

Required metadata fields for successful analyze responses:

| Field | Type | Rule |
|---|---|---|
| `retrieval_count` | int | Number of final retrieved sources returned to prompt/response. |
| `has_sources` | bool | `true` if `retrieval_count > 0`. |
| `retrieval_strategy` | string | Example: `in_memory_keyword_v1`. |

Recommended optional internal/debug metadata:

| Field | Type | Rule |
|---|---|---|
| `top_score` | float/null | Internal debug only. |
| `retrieved_source_ids` | string[] | Internal debug only; do not show to users. |
| `source_status_counts` | object | Useful for tests. |
| `no_source_reason` | string/null | Useful when `sources: []`. |

Do not expose:

- API keys;
- raw provider errors;
- hidden prompts;
- private logs;
- user personal data;
- cross-chat content.

---

## 24. Failure Classification

RAG failure behavior must match `api_contract.md` and `ai_core_spec.md`.

| Event | Analyze result | HTTP status |
|---|---|---:|
| `legal_snippets.json` missing, corrupt, or unreadable | API error, `error.code: retrieval_error` | `503` |
| Required snippet fields missing at startup | API error, `error.code: retrieval_error` | `503` |
| RAG returns zero relevant sources | Success response, `sources: []` | `200` |
| A deprecated snippet exists in file | Not an error; must be excluded | `200` if request otherwise succeeds |
| All matching sources are deprecated | Success response, `sources: []` | `200` |

Rule:

```text
Broken source store = retrieval_error.
No relevant source = normal successful response with cautious answer.
```

### 24.1. Health check behavior

Startup validation must expose RAG health through `GET /api/health`.

Recommended health fields:

```json
{
  "status": "ok",
  "rag_loaded": true,
  "snippet_count": 26
}
```

`snippet_count` is an additive debug field for implementation visibility. It is not required by `api_contract.md` Section 19.

If `legal_snippets.json` cannot load or validate:

```json
{
  "status": "degraded",
  "rag_loaded": false,
  "snippet_count": 0
}
```

Analyze behavior in degraded RAG state:

```text
POST /api/analyze → retrieval_error HTTP 503
```

Do not silently continue with an empty source pack when the source file is broken. Empty retrieval from a healthy source pack is normal; broken source store is not.

## 25. Optional Retrieval Backends

### 25.1. Option A — In-memory JSON search

Recommended for MVP v1.

Pros:

- fastest to implement;
- no database dependency;
- deterministic;
- easy to debug;
- enough for 20–100 snippets.

Cons:

- not scalable;
- weaker semantic search.

Use this first.

### 25.2. Option B — SQLite FTS5

Good post-MVP or late-MVP upgrade.

Pros:

- still local and simple;
- better keyword search;
- can support larger source pack.

Cons:

- requires indexing setup;
- more code and tests.

Use only after in-memory retrieval passes golden cases.

### 25.3. Option C — Vector search

Not required for MVP v1.

Possible future tools:

- FAISS;
- Chroma;
- LanceDB;
- pgvector;
- embedding cache.

Do not start here for portfolio/competition MVP. It adds complexity before proving core product behavior.

---

## 26. RAG Evaluation

RAG must be evaluated with golden and demo cases.

Minimum checks:

- civil deposit case returns a civil/deposit/rental source;
- traffic fine case returns a traffic source;
- household business/food online case returns business or food safety source;
- unsafe traffic evasion returns high-risk/safety source or no harmful source;
- no deprecated snippet is returned;
- no fabricated source id/url/title appears;
- no-source behavior returns `sources: []` and cautious content;
- Vietnamese without diacritics retrieves correctly;
- follow-up query in same chat retrieves based on same-chat context;
- the same generic follow-up query without context returns `sources: []`.

Suggested metrics:

| Metric | MVP target |
|---|---:|
| Demo case source presence | 100% |
| Deprecated source count | 0 |
| Fabricated source count | 0 |
| Domain match rate on golden cases | >= 80% |
| Unsafe query harmful source count | 0 |
| No-source cautious behavior | 100% |
| Vietnamese no-diacritics retrieval pass | 100% for required demo/golden cases |
| Follow-up retrieval pass | 100% for required follow-up demo case |

---

## 27. RAG Test Cases

Minimum RAG tests:

| ID | Query | Context | Expected |
|---|---|---|---|
| `rag_001` | Tôi thuê nhà, chủ nhà giữ tiền cọc không trả. | none | Returns civil/deposit source. |
| `rag_002` | Bạn tôi vay tiền không trả. | none | Returns civil loan/evidence source. |
| `rag_003` | Tôi bị phạt giao thông nhưng không hiểu lỗi. | none | Returns traffic source. |
| `rag_004` | Tôi muốn bán đồ ăn online ở quê. | none | Returns household business or food safety source. |
| `rag_005` | Làm sao để né phạt giao thông? | unsafe high-risk | Returns safety/high-risk source or no harmful source. |
| `rag_006` | lam sao de ne phat giao thong | unsafe high-risk | Same as `rag_005`. |
| `rag_007` | Tôi bị công an mời làm việc. | high-risk | Returns high-risk/professional help source if available. |
| `rag_008` | Viết cho tôi bài thơ tình. | unsupported | Returns no source. |
| `rag_009` | Query unrelated to any snippet | none | Returns empty sources and has_sources false. |
| `rag_010` | Deprecated snippet exists | none | Deprecated snippet is never returned. |
| `rag_011` | Vậy tôi cần chuẩn bị giấy tờ gì? | same chat previously about rental deposit | Returns civil/deposit/rental checklist source. |
| `rag_011b` | Vậy tôi cần chuẩn bị giấy tờ gì? | none | Returns empty sources; generic follow-up text alone must not pass the content gate. |
| `rag_012` | toi thue nha chu nha giu tien coc khong tra | none | Returns civil/deposit source. |
| `rag_013` | toi muon ban do an online o que can giay to gi | none | Returns household business/food source. |

---

## 28. Implementation Requirements for Teammate

The RAG owner must implement:

1. `backend/app/rag_retriever.py`
2. startup source loading and validation;
3. accent-insensitive normalization support;
4. domain/tag/text scoring;
5. deprecated source exclusion;
6. top-k selection;
7. no-source behavior;
8. retrieval metadata;
9. retrieval tests;
10. integration with Prompt Builder using `allowed_source_ids`;
11. integration with Citation Guard using `used_source_ids`;
12. integration with Response Builder mapping source ids to API source objects.

Recommended internal classes/functions:

```python
class LegalSnippet:
    id: str
    domain: str
    title: str
    source_name: str
    source_url: str | None
    source_type: str
    status: str
    text: str
    plain_language_summary: str | None
    tags: list[str]
    risk_notes: list[str]
    last_checked: str

class RetrievedSource(LegalSnippet):
    score: float

class RetrievalResult:
    sources: list[RetrievedSource]
    allowed_source_ids: list[str]
    retrieval_count: int
    has_sources: bool
    retrieval_strategy: str
```

Suggested functions:

```python
load_snippets(path: str) -> list[LegalSnippet]
validate_snippet(snippet: dict) -> LegalSnippet
normalize_for_retrieval(text: str) -> str
retrieve_sources(...) -> RetrievalResult
map_sources_for_api(used_source_ids: list[str], retrieved_sources: list[RetrievedSource]) -> list[ApiSource]
```

`map_sources_for_api` may live in `response_builder.py`, but the mapping rules must follow this document.

---

## 29. Implementation Order

Build in this order:

1. Load `legal_snippets.json`.
2. Validate required fields.
3. Add normalization + accent-insensitive matching.
4. Exclude deprecated snippets.
5. Implement simple scoring.
6. Return top 1–3 sources.
7. Return `allowed_source_ids`.
8. Add no-source behavior.
9. Add metadata.
10. Add tests for 3 demo cases.
11. Add unsafe query test.
12. Add Vietnamese no-diacritics tests.
13. Add follow-up retrieval tests with and without same-chat context.
14. Integrate with Prompt Builder.
15. Integrate with Citation Guard and Response Builder.

Do not add vector search before steps 1–15 pass.

---

## 30. Definition of Done

RAG MVP is done when:

- source file loads successfully;
- invalid/corrupt source file returns `retrieval_error` HTTP 503;
- deprecated snippets are excluded;
- top 1–3 sources are returned for all 3 demo cases;
- unsafe query does not return harmful how-to source;
- no-source case returns empty sources;
- Vietnamese without diacritics retrieves correctly;
- follow-up query retrieves using same-chat context;
- generic follow-up query without context does not retrieve unrelated sources;
- LLM receives retrieved sources and `allowed_source_ids`;
- LLM output uses only `used_source_ids`;
- invalid `used_source_ids` are removed by Citation Guard;
- final API source objects match contract;
- no fabricated source id/url/law/article appears;
- tests pass.

---

## 31. MVP RAG Rule

For this MVP, the correct RAG strategy is:

```text
Small curated source pack
+ deterministic in-memory retrieval
+ domain/tag/text scoring
+ accent-insensitive Vietnamese matching
+ used_source_ids boundary
+ citation guard
+ cautious no-source behavior
```

Do not overbuild vector infrastructure before the product proves the core legal navigation workflow.

