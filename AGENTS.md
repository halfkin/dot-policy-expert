# Agents

Shared instructions for all AI models working on this project.

## Project Overview
Dot is a grounded RAG chatbot for policy Q&A. See README.md for full context.

## Architecture
- `backend/app.py` — FastAPI routes and orchestration
- `backend/kb_loader.py` — Markdown chunking and KB loading
- `backend/retrieval.py` — Blended keyword + semantic search, scoring, re-ranking
- `backend/llm_client.py` — OpenRouter LLM calls
- `backend/language.py` — Language detection and translation
- `backend/conflict_detector.py` — Numeric fact extraction, tier-aware comparison, LLM verification
- `backend/ravelin.py` — 4-layer prompt injection defense
- `backend/embedder.py` — Sentence-transformer embeddings
- `backend/reranker.py` — Cross-encoder re-ranking
- `backend/query_reformulator.py` — Query rewriting for retrieval
- `frontend/index.html` — Single-page chat UI
- `kb/` — Markdown knowledge base (swappable)
- `evals/` — Two eval suites (see evals/README.md)

## Key Principles
- Doc-agnostic: no hardcoded KB references in retrieval or detection logic
- Tiered cost: cheap checks first (regex, Jaccard), expensive LLM only when needed
- Fail-open: LLM/API failures → safe defaults, never block users
- Every factual answer must cite at least one KB chunk

## Testing
- Unit tests: `pytest tests/`
- Eval suite: `python evals/eval_loomo.py` (current: 54/58, 93.1%)
- Dot must be running for eval: `uvicorn backend.app:app --port 8000`

## Environment
- Python 3.11, FastAPI, sentence-transformers
- Config via .env (see .env.example)
- KB swappable via volume mount or file replacement
