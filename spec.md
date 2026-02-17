# Moats Verify — Product Specification

## 1. Purpose

Moats Verify evaluates whether factual claims are supported by a user-managed document library.

Primary output is a structured verification report with per-claim verdicts, confidence, explanation, and source citation.

## 2. Scope

In scope:

- Claim extraction from free-form input text
- Evidence retrieval from library chunks in ChromaDB
- FlashRank reranking
- Deterministic comparison for numeric/temporal/polarity checks
- LLM fallback reasoning when deterministic comparison is inconclusive
- Verification history and JSON export

Out of scope (current version):

- External connector verification flows
- Graph-based retrieval in active verification path
- Autonomous source quality scoring

## 3. User workflows

### 3.1 Configure model provider

User sets provider and model config in Settings (`provider`, `api_key`, `base_url`, `chat_model`, `embedding_model`).

### 3.2 Build library

User creates/activates a library, adds sources (upload, local folder, or existing ChromaDB), and runs sync/build.

### 3.3 Verify text

User submits text. System returns:

- Aggregate trust score
- List of per-claim verdicts
- Evidence snippets and citations
- `used_llm` indicator (`true`/`false`) per claim

## 4. Verification pipeline

1. Claim segmentation from input text.
2. Structured extraction per claim:
   - numeric values
   - temporal expressions
   - subject and polarity cues
3. Retrieval from ChromaDB using embedding search.
4. FlashRank reranking of candidates.
5. Relevance gate:
   - If top rerank score is below threshold (`0.3`), treat as `NO_EVIDENCE`.
6. Comparison:
   - numeric tolerance checks
   - temporal overlap checks
   - polarity consistency checks
7. If comparison is inconclusive, use LLM reasoning fallback.
8. Return standardized verdict object.

## 5. Verdict model

Allowed verdicts:

- `SUPPORTED`
- `PARTIALLY_SUPPORTED`
- `CONTRADICTED`
- `NO_EVIDENCE`

Per-claim fields:

- `claim`
- `verdict`
- `confidence` (float)
- `reason`
- `evidence` (`text`, `source`, `page`)
- `used_llm` (boolean)

## 6. Trust score

Weighted aggregate across claims with evidence:

- `SUPPORTED`: 1.0
- `PARTIALLY_SUPPORTED`: 0.6
- `CONTRADICTED`: 0.0
- `NO_EVIDENCE`: excluded

If all claims are `NO_EVIDENCE`, UI displays **Insufficient Evidence**.

## 7. Storage

- SQLite: libraries, sources, build jobs, verification history
- ChromaDB: chunk embeddings and retrieval
- Local filesystem: uploads and extracted runtime data under `data/`

## 8. API contract summary

Core endpoints:

- `POST /api/verify`
- `GET /api/verify/history`
- `GET /api/verify/{id}`
- `POST /api/libraries/{id}/upload`
- `POST /api/libraries/{id}/build`
- `PUT /api/settings/llm`
- `POST /api/settings/llm/test`

## 9. Non-functional requirements

- Async request handling for API paths
- Deterministic fallback path when LLM is unavailable
- Clear provenance for evidence and verdict reason
- Local-first data handling; no automatic external data export
