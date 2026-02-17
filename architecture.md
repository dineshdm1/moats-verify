# Moats Verify — Architecture

## 1. Runtime topology

- **Frontend**: Next.js app on port `3000`
- **Backend**: FastAPI app on port `8000`
- **Stores**:
  - SQLite for metadata/history
  - ChromaDB (persistent local directory) for vectors

Docker Compose runs frontend and backend as separate services, with persistent data mounted under `/data` in the backend container.

## 2. Backend component map

### API layer

- `backend/main.py`: app bootstrap, dependency singletons, CORS, router registration
- `backend/api/routes/verify.py`: verification endpoints and history/export
- `backend/api/routes/libraries.py`: library lifecycle and build jobs
- `backend/api/routes/sources.py`: source management, upload, folder ingestion, ChromaDB connect
- `backend/api/routes/settings.py`: LLM settings update and connection tests

### Core verification pipeline

- `backend/core/segmenter.py`: claim segmentation
- `backend/core/extractor.py`: structured signal extraction (numeric/temporal/polarity)
- `backend/core/retrieval.py`: embedding search + FlashRank reranking + relevance threshold
- `backend/core/comparator.py`: deterministic comparison logic
- `backend/core/verdict.py`: verdict generation with optional LLM fallback
- `backend/core/pipeline.py`: orchestration and trust score aggregation

### Ingestion and storage

- `backend/ingestion/ingest.py`: parsing/chunking/embedding ingestion jobs
- `backend/storage/sqlite.py`: metadata and verification persistence
- `backend/storage/chromadb.py`: vector insert/query operations

### LLM abstraction

- `backend/llm/provider.py`: unified interface for chat completion and embeddings

## 3. Verification request flow

1. `POST /api/verify` receives text and resolves active library.
2. Pipeline extracts claims and structured attributes.
3. Retriever queries ChromaDB and reranks with FlashRank.
4. If top rerank score is below threshold, claim is marked `NO_EVIDENCE`.
5. Comparator attempts deterministic decision.
6. If needed, verdict module performs LLM reasoning fallback.
7. Response is persisted and returned with per-claim evidence, reason, confidence, and `used_llm`.

## 4. Data model (high level)

### SQLite

- Libraries and active library marker
- Sources and source configuration
- Documents/chunks metadata
- Build jobs
- Verification records and claim payloads
- Settings (`llm_config`)

### ChromaDB

- Per-library collection namespace
- Embeddings + metadata for retrieval candidates

## 5. Frontend architecture

- `frontend/src/app/page.tsx`: verify input and submission
- `frontend/src/app/library/page.tsx`: source and build operations
- `frontend/src/app/settings/page.tsx`: provider and model configuration
- `frontend/src/app/results/[id]/page.tsx`: verification report rendering
- `frontend/src/components/verify/VerdictCard.tsx`: per-claim card with verdict, reason, evidence, and method indicator

## 6. Operational notes

- Data directories (`data/`, `library/`) are local runtime artifacts and should not be committed.
- Legacy verification modules are retained under `backend/deprecated/` for rollback only.
- The active verification path is `backend/core/*`.
- Docker Compose currently includes a Neo4j service for compatibility; it is not used by the active `backend/core/*` verification flow.
