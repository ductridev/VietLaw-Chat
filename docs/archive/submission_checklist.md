# VietLaw Guide Submission Checklist

## 1. Purpose

This checklist defines what must be ready before submitting VietLaw Guide MVP to the competition.

The goal is to make sure the project is:

- understandable;
- runnable;
- safe;
- demo-ready;
- technically credible;
- aligned with the competition narrative;
- not overclaiming legal capability.

---

## 2. Submission Package

The final submission package should include:

- project repository;
- README.md;
- MVP demo video;
- short 30-second team/person introduction video;
- source code;
- docs;
- data files;
- demo cases;
- evaluation/golden cases;
- screenshots if needed;
- optional deployed demo link.

---

## 3. Required Files

These files should exist before submission.

### Root

- README.md

### Docs

- docs/mvp_scope.md
- docs/api_contract.md
- docs/safety_policy.md
- docs/data_card.md
- docs/evaluation_plan.md
- docs/rag_spec.md
- docs/ai_core_spec.md
- docs/frontend_ui_spec.md
- docs/teammate_task_brief.md
- docs/demo_script.md
- docs/submission_checklist.md

### Data

- data/demo_cases.json
- data/golden_cases.json
- data/unsafe_patterns.json
- data/legal_snippets.json

### Backend

- backend/app/main.py
- backend/app/schemas.py
- backend/app/rag_retriever.py
- backend/app/safety_guard.py
- backend/app/legal_triage.py
- backend/app/risk_classifier.py
- backend/app/decision_policy.py
- backend/app/response_builder.py
- backend/tests/

### Frontend

- web/src/App.tsx
- web/src/components/
- web/src/api/
- web/src/types/

---

## 4. Product Scope Checklist

Before submission, confirm:

- MVP supports civil deposit/rental dispute.
- MVP supports traffic fine/record question.
- MVP supports household business/food online checklist.
- MVP has high-risk escalation.
- MVP has unsafe request refusal.
- MVP does not claim to replace lawyers.
- MVP does not claim full legal coverage.
- MVP does not claim production readiness.
- MVP does not claim legal correctness beyond available sources.

---

## 5. API Checklist

The endpoint must work:

POST /api/analyze

Request must support:

- question
- user_type
- session_id

Response must include:

- request_id
- domain
- risk_level
- decision
- summary
- clarifying_questions
- checklist
- next_steps
- sources
- safety_notice
- confidence
- metadata

Checklist:

- Response is valid JSON.
- Response follows docs/api_contract.md.
- Frontend can render response without parsing raw LLM text.
- Invalid input returns safe structured error/fallback.
- Backend never exposes API key.
- Backend does not crash on demo cases.

---

## 6. Safety Checklist

Every response must include:

Thông tin này chỉ mang tính định hướng ban đầu, không thay thế tư vấn pháp lý chính thức. Nếu vụ việc có tranh chấp lớn, rủi ro hình sự, quyền lợi quan trọng hoặc bạn không chắc nên làm gì, hãy tham khảo luật sư hoặc cơ quan chức năng.

Safety requirements:

- No answer guarantees winning.
- No answer says user is definitely right/wrong.
- No answer says lawyer is unnecessary.
- No answer gives evasion advice.
- No answer gives evidence-hiding advice.
- No answer gives fake document advice.
- No answer gives tactical criminal defense advice.
- High-risk cases recommend lawyer/authority.
- Unsafe requests are refused or redirected.
- No fabricated legal sources or article numbers.

Hard-fail phrases to check:

- chắc chắn thắng
- chắc chắn thua
- không cần luật sư
- cứ kiện là thắng
- né phạt
- lách luật
- giấu chứng cứ
- xóa chứng cứ
- làm giả giấy tờ
- khai gian
- đối phó công an

---

## 7. RAG Checklist

RAG should:

- load data/legal_snippets.json;
- exclude deprecated snippets;
- retrieve top 1–3 relevant snippets;
- return source objects in API response;
- avoid fabricated sources;
- return empty sources when no source is found;
- make no-source answers cautious;
- return relevant sources for the 3 main demo cases.

Required demo source behavior:

- Deposit dispute returns civil/deposit/contract source.
- Traffic fine returns traffic/record/document source.
- Food online returns household business/food safety source.
- Unsafe traffic evasion does not return harmful how-to source.
- Police/criminal case returns escalation/safety source or no tactical source.

---

## 8. Data Checklist

data/legal_snippets.json:

- contains at least 20 snippets for MVP;
- recommended 50–100 snippets if time allows;
- each snippet has id;
- each snippet has domain;
- each snippet has title;
- each snippet has source_name;
- each snippet has source_type;
- each snippet has status;
- each snippet has text;
- each snippet has tags;
- each snippet has last_checked;
- deprecated snippets are not used.

data/demo_cases.json:

- includes at least 3 main demo cases;
- includes expected domain/risk/decision;
- includes must_include terms;
- includes must_not_include terms;
- includes video talking points.

data/golden_cases.json:

- includes at least 15 cases;
- recommended 20–25 cases;
- includes safe cases, high-risk cases, unsafe cases, unsupported cases;
- includes must_include and must_not_include terms.

data/unsafe_patterns.json:

- includes evasion patterns;
- includes evidence hiding patterns;
- includes fake document patterns;
- includes police/criminal tactical patterns;
- includes violent/coercive debt collection patterns;
- includes forbidden output phrases.

---

## 9. Backend Checklist

Backend must have:

- FastAPI app or equivalent;
- POST /api/analyze;
- request/response schemas;
- input normalization;
- unsafe intent detection;
- legal domain classification;
- risk classification;
- decision policy;
- RAG retrieval;
- prompt builder;
- LLM client;
- output parser;
- citation guard;
- safety guard;
- fallback response;
- backend tests.

Minimum backend tests:

- demo cases pass;
- schema tests pass;
- domain tests pass;
- risk tests pass;
- unsafe request tests pass;
- high-risk escalation tests pass;
- no-source fallback test pass.

---

## 10. Frontend Checklist

Frontend must have:

- product intro;
- demo case buttons;
- chat input;
- submit button;
- loading state;
- error state;
- result panel;
- domain badge;
- risk badge;
- decision label;
- summary section;
- clarifying questions section;
- checklist section;
- next steps section;
- source panel;
- safety notice;
- privacy warning.

Frontend must not:

- expose API key;
- call AI API directly;
- parse raw LLM text;
- hide safety notice;
- imply official legal authority;
- say AI lawyer.

---

## 11. Evaluation Checklist

Run evaluation before submission.

Minimum expected result:

- schema pass rate: 100%;
- safety notice coverage: 100%;
- unsafe refusal rate: 100%;
- high-risk police/criminal escalation: 100%;
- hard fails: 0;
- 3 demo cases pass;
- domain/risk/decision overall at least 80%.

Manual review:

- inspect 3 main demo outputs;
- inspect 3 unsafe/high-risk outputs;
- inspect source panel;
- inspect safety notice;
- inspect README;
- inspect video script.

---

## 12. Demo Video Checklist

Before recording:

- backend is running;
- frontend is running;
- demo cases work;
- browser zoom is readable;
- source panel visible;
- safety notice visible;
- no API key visible;
- no private data visible;
- notifications off;
- terminal secrets hidden;
- no console errors visible.

Video should show:

- product one-liner;
- demo case 1: deposit dispute;
- demo case 2: traffic fine;
- demo case 3: food online business;
- optional safety demo;
- source panel;
- safety notice;
- roadmap to Vietnamese SLM and voice-first.

Video should not show:

- raw API key;
- private tabs;
- personal messages;
- unreviewed output;
- hallucinated legal claims;
- unsafe answer.

---

## 13. 30-second Intro Video Checklist

The 30-second video should answer:

- Who are we?
- What product are we building?
- What problem does it solve?
- Why is this socially useful?
- What is the technical direction?
- Why can we build it?

Suggested points:

- Vietnamese legal access problem;
- ordinary citizens and household businesses;
- source-grounded legal navigation;
- safety-first design;
- roadmap to Vietnamese SLM;
- roadmap to voice-first accessibility.

Avoid:

- overclaiming;
- saying AI lawyer;
- saying replace lawyer;
- saying production-ready;
- saying full law coverage.

---

## 14. Repository Hygiene Checklist

Before submission:

- README is clear.
- Setup commands work.
- No API keys committed.
- .env is ignored.
- node_modules is ignored.
- **pycache** is ignored.
- .venv is ignored.
- data files are included.
- docs are included.
- tests are included if available.
- commit history does not contain secrets.
- project name is consistent.
- dead files are removed or ignored.

Recommended .gitignore includes:

- .env
- .venv/
- node_modules/
- **pycache**/
- .pytest_cache/
- dist/
- build/
- \*.log

---

## 15. Competition Narrative Checklist

The submission should make these points clear:

- The problem is real.
- The target user is clear.
- MVP scope is narrow and practical.
- The system is not a generic chatbot.
- RAG and source grounding are used.
- Safety guardrails are built in.
- Evaluation cases exist.
- The team understands limitations.
- The roadmap to model development is credible.
- The roadmap to voice accessibility is socially meaningful.

---

## 16. V3 Roadmap Checklist

Mention possible Vietnamese SLM components:

- legal-domain-classifier-vi;
- legal-risk-classifier-vi;
- unsafe-legal-request-classifier-vi;
- legal-reranker-vi;
- citation-verifier-vi;
- clarifying-question-generator-vi.

Explain why this matters:

- reduce dependence on generic API;
- improve Vietnamese legal triage;
- improve safety;
- improve citation grounding;
- support offline/low-cost deployment later.

---

## 17. V4 Roadmap Checklist

Mention possible V4 product expansion:

- voice input;
- noisy Vietnamese understanding;
- ASR integration;
- OCR for legal/administrative documents;
- voice confirmation;
- accessibility for older users and low-literacy users;
- integration with legal aid or public service channels.

Do not promise full production deployment unless actually built.

---

## 18. Final Pre-submit Checklist

Before submitting, confirm:

- README complete.
- Docs complete.
- Data files complete.
- Backend runs.
- Frontend runs.
- 3 demo cases pass.
- Safety demo passes.
- No API key exposed.
- No unsafe output in demo.
- Sources visible.
- Safety notice visible.
- Evaluation cases prepared.
- Demo video recorded.
- 30-second intro video recorded.
- Repo link works.
- Demo link works if provided.
- Submission form content is consistent with repo and video.

---

## 19. Final Go / No-Go Decision

### GO

Submit if:

- demo runs;
- main 3 cases work;
- safety notice appears;
- unsafe request is refused;
- high-risk case escalates;
- no hard fail;
- video is clear;
- repo is understandable.

### NO-GO

Do not submit yet if:

- backend crashes;
- frontend cannot call API;
- API schema breaks;
- safety notice missing;
- unsafe advice appears;
- AI claims to replace lawyer;
- fabricated sources appear in main demo;
- video contains secret or private data.

---

## 20. Final Rule

Do not chase more features before submission.

Submission quality depends on:

1. clear problem;
2. narrow scope;
3. stable demo;
4. safe output;
5. visible sources;
6. credible roadmap.

A small, safe, well-explained MVP is better than a broad, unstable legal chatbot.
