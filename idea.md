# Moats Intelligence

**Verify. Detect. Decide.**

An intelligence workbench that reads your documents and tells you what conflicts, what's missing, and what to trust.

---

## The Problem

Every knowledge worker drowns in documents. They can search them. What they can't do:

- Know which of their sources **contradict each other**
- See where their research has **blind spots**
- Verify whether a claim is **backed by evidence** or invented
- Get a **brief on what changed** since they last looked

Today this takes a human analyst days or weeks. Consultancies charge $500K+ per engagement for exactly this work.

## The Product

Three intelligence actions, each producing structured, verifiable output.

### Core Actions

**VERIFY** — "Is this claim true?" (Built)
- User pastes text (a deck, a memo, a competitor quote, a news article)
- System extracts every factual claim
- Each claim is checked against the full document library
- Output: structured verdict table — Supported / Contradicted / No Evidence
- Every verdict links to the exact source passage and page number

**GAPS** — "What am I missing?" (Planned)
- System scans the knowledge graph across all ingested documents
- Shows topic coverage density — what's well-covered vs. thin
- Identifies blind spots: topics that related documents reference but the user has zero coverage on
- Output: coverage map with density scores and gap recommendations

**CONTRADICTIONS** — "Where do my sources disagree?" (Planned)
- System finds semantically similar passages that make opposing claims
- Shows them side by side: Source A says X (page 14) vs. Source B says Y (page 87)
- No LLM opinion — just the raw conflict for the user to judge
- Output: list of contradictions ranked by confidence

---

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **Frontend** | Next.js 14, shadcn/ui, Zustand | Verify page, library management, results display |
| **Backend** | FastAPI | REST API, verification pipeline, ingestion |
| **LLM** | OpenRouter | Claim extraction, contradiction detection, verdict generation |
| **Vector Store** | ChromaDB | Semantic search with HNSW tuning |
| **Reranker** | FlashRank | Cross-encoder reranking |
| **Knowledge Graph** | Neo4j 5 | Entity relationships, graph-enhanced retrieval |
| **Metadata** | SQLite | Documents, verifications, build jobs |
| **Ingestion** | PyMuPDF, ebooklib, python-docx | PDF, EPUB, DOCX, TXT, MD processing |

## Design Principles

- **Dashboard-first, not chat-first.** System surfaces intelligence. User drills down.
- **LLM as pattern detector, not content generator.** Finds contradictions, gaps, and evidence. Never writes original content.
- **Structured, verifiable output.** Every claim links to an exact passage and page number. No unverifiable prose.
- **Ultra-minimalist interface.** Clean, no clutter. Every element earns its screen space.

## Build Order

1. ~~VERIFY~~ (Done)
2. GAPS — leverages existing knowledge graph
3. CONTRADICTIONS — leverages existing knowledge graph
4. Intelligence brief — auto-generated on each session start
5. Investigate chat — context-aware drill-down into any finding
