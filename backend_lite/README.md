# VietLaw-Chat Backend Lite

`backend_lite/` is the deterministic reference backend for frontend UX/UI and API-contract testing. It is a real FastAPI + SQLite implementation, but it uses lexical RAG, deterministic classifiers and reusable templates instead of an external model.

`backend/` is a separate production implementation owned by another team member. Backend Lite never imports, modifies, starts, or shares its database with `backend/`.

## Requirements and setup

- Python 3.11+
- Node 20 for the frontend (`.nvmrc`)

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend_lite/requirements.txt
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BACKEND_MODE` | `lite` | Identifies the deterministic runtime. |
| `CHAT_DB_PATH` | `./data/vietlaw_chat.sqlite3` | Lite-only SQLite chat database. |
| `LEGAL_SNIPPETS_PATH` | `./data/legal_snippets.json` | Curated RAG input. |
| `UNSAFE_PATTERNS_PATH` | `./data/unsafe_patterns.json` | Unsafe/high-risk patterns. |
| `CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | Allowed frontend origins. |
| `RAG_TOP_K` | `3` | Maximum relevant sources. |
| `CONTEXT_MESSAGE_LIMIT` | `8` | Recent same-chat messages. |

Backend Lite needs no API key. Override `CHAT_DB_PATH` when running tests or parallel implementations. The default DB is ignored by Git and can be reset locally with:

```bash
rm -f data/vietlaw_chat.sqlite3
```

## Run on port 8010

The official command is:

```bash
.venv/bin/python -m uvicorn backend_lite.app.main:app \
  --host 127.0.0.1 \
  --port 8010
```

Health check:

```bash
curl http://127.0.0.1:8010/api/health
```

Backend production is expected on port 8000; do not substitute its package or database paths into this command.

## Tests and evaluation

```bash
.venv/bin/python -m py_compile $(find backend_lite -name '*.py' -type f)
.venv/bin/python -m pytest backend_lite/tests --collect-only -q
.venv/bin/python -m pytest backend_lite/tests -q
```

Tests use temporary SQLite databases. When a TCP server is available, evaluation can run with:

```bash
.venv/bin/python scripts/run_eval.py --base-url http://127.0.0.1:8010
```

## Frontend integration

Run the Vite frontend against Lite with:

```bash
cd frontend
VITE_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

The frontend sends `session_id` with analyze, chat detail and deletion. Chat detail uses `GET /api/chats/{chat_id}?session_id=...`; deletion uses the equivalent `DELETE` URL. Wrong-session, deleted and missing chats all return the same 404 `chat_not_found` envelope.

## Runtime and extension boundary

`AgentRuntime` owns the 18 analyze phases. A generator returns only content plus `used_source_ids`, and advertises `model_name`/`used_llm`. CitationGuard filters source IDs and cautions unsupported claims; SafetyGuard scans generated fields and can replace unsafe content before ResponseBuilder builds and validates the final response.

A future `LLMContentGenerator` should implement the same `ContentGenerator` protocol and be selected only in the composition root. Routes, storage, API schemas and frontend do not need to change, but production integration must add provider error handling and robust output parsing/fallback.

## Limitations

- RAG is lexical/topic-gated, not semantic vector retrieval.
- Legal coverage is limited to the curated MVP data.
- There is no login; `session_id` is the required no-login ownership boundary, not strong authentication.
- Same-chat requests are not serialized in-process. The frontend blocks duplicate submit, but simultaneous multi-tab requests can interleave.
- A pipeline failure after the user message is stored leaves a deterministic user-only partial turn; the invalid assistant response is never stored.
- Browser click-through and visual correctness require separate manual verification.
