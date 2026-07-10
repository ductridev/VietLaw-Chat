# VietLaw-Chat Snippet Authoring

This directory is the human-editable source for the RAG data pack.

## MVP rule

Edit Markdown files here, then rebuild the runtime JSON:

```bash
python scripts/build_snippets.py
```

The app runtime must read only:

```text
data/legal_snippets.json
```

Do not make backend/RAG code read Markdown directly.

## Required Markdown format

```markdown
---
id: civil_deposit_001
domain: civil_dispute
source_name: "Bộ luật Dân sự 2015 - Điều 328"
source_url: "https://example.gov.vn/source"
source_type: official_source
status: active
tags: ["dat_coc", "tien_coc", "hop_dong"]
risk_notes: ["medium_risk", "money_dispute"]
last_checked: 2026-07-10
---
# Đặt cọc để bảo đảm giao kết hoặc thực hiện hợp đồng

## Text
Main source text used for retrieval and grounding.

## Plain summary
Short plain-language Vietnamese explanation.
```

## Important

- Commit both `data/snippets_md/*.md` and generated `data/legal_snippets.json`.
- Do not edit `data/legal_snippets.json` manually unless you are intentionally fixing a generated artifact.
- Keep `id` stable after it is referenced by demo or golden cases.
- Runtime startup validation still validates `data/legal_snippets.json`; compile-time validation does not replace runtime validation.
