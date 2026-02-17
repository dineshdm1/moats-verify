# Moats Verify

Moats Verify checks AI-generated text against your document library and returns per-claim verdicts with citations.

## What it does

Verify AI-generated text against your documents.

Works for RAG output, report fact-checking, compliance review, or any text you want to verify against source documents.

- Extracts factual claims from input text
- Retrieves candidate evidence from ChromaDB
- Re-ranks evidence with FlashRank
- Applies structured comparison (numeric, temporal, polarity)
- Falls back to LLM reasoning when structured comparison is inconclusive
- Returns `SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONTRADICTED`, or `NO_EVIDENCE`

## Requirements

- Docker Desktop (or Docker Engine + Compose plugin)
- An LLM provider key (OpenRouter/OpenAI/Anthropic) or a local OpenAI-compatible endpoint

## Quick start (Docker, no local pip)

```bash
cp .env.example .env && docker compose up --build
```

Then open:

- App UI: http://localhost:3000
- API docs: http://localhost:8000/docs

Note: the Compose stack also starts a Neo4j container for backward compatibility. The active verification pipeline uses SQLite + ChromaDB.

## First run checklist

1. Open **Settings** and configure provider, chat model, and embedding model.
2. Open **Library** and create a library.
3. Add documents via upload or local folder source.
4. Run **Sync/Build** to ingest and embed documents.
5. Open **Verify** and submit text.

## Verify API example

```bash
curl -X POST http://localhost:8000/api/verify \
  -H "Content-Type: application/json" \
  -d '{"text":"Revenue was $5M in Q3 2024"}'
```

Response includes:

- `verdict`
- `confidence`
- `reason`
- `evidence` (`text`, `source`, `page`)
- `used_llm` (`true` = reasoning fallback, `false` = structured comparison)

## Data and privacy

- Runtime data is stored locally under `./data/` and Docker volumes.
- User document folders are mounted read-only from `./library/`.
- `.env`, `library/`, and `data/` are git-ignored.

## Development (without Docker)

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

In another shell:

```bash
cd frontend && npm install && npm run dev
```

## Project layout

- `backend/`: FastAPI API, ingestion, retrieval, verification pipeline
- `frontend/`: Next.js UI
- `tests/`: backend tests
- `backend/deprecated/`: legacy verify stack kept for rollback

## Troubleshooting

- Empty verification results: confirm library has indexed chunks.
- `NO_EVIDENCE` for known claims: confirm the relevant documents are in the active library.
- LLM errors: validate provider settings on **Settings** page.

## License

This project is licensed under the MIT License. See `LICENSE`.
