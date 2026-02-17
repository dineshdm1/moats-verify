"""Tests for core retrieval (Chroma + FlashRank thresholding)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

import backend.core.retrieval as retrieval_module
from backend.core.retrieval import EvidenceRetriever


@pytest.fixture
def mock_vector_store():
    store = MagicMock()
    store.search.return_value = [
        {
            "text": "Revenue reached $5.0M in Q3 2024.",
            "metadata": {"document_id": 1, "document_title": "Report.pdf", "start_page": 10},
            "similarity": 0.9,
        },
        {
            "text": "Operating costs increased.",
            "metadata": {"document_id": 2, "document_title": "Ops.pdf", "start_page": 4},
            "similarity": 0.6,
        },
    ]
    return store


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.embed_single.return_value = [0.1] * 8
    return llm


class _FakeRanker:
    def __init__(self, scores: list[float]):
        self._scores = scores

    def rerank(self, request):
        results = []
        for idx, passage in enumerate(request.passages):
            results.append({"meta": {"index": passage["meta"]["index"]}, "score": self._scores[idx]})
        return results


@pytest.mark.asyncio
async def test_retrieval_drops_low_rerank_score(monkeypatch, mock_vector_store, mock_llm):
    monkeypatch.setattr(retrieval_module, "_get_reranker", lambda: _FakeRanker([0.12, 0.10]))

    retriever = EvidenceRetriever(mock_vector_store, mock_llm, min_rerank_score=0.3)
    evidence = await retriever.retrieve("Revenue was $5M", "lib1", top_k=2)

    assert evidence == []


@pytest.mark.asyncio
async def test_retrieval_keeps_high_rerank_score(monkeypatch, mock_vector_store, mock_llm):
    monkeypatch.setattr(retrieval_module, "_get_reranker", lambda: _FakeRanker([0.82, 0.41]))

    retriever = EvidenceRetriever(mock_vector_store, mock_llm, min_rerank_score=0.3)
    evidence = await retriever.retrieve("Revenue was $5M", "lib1", top_k=2)

    assert len(evidence) == 2
    assert evidence[0]["source"] == "Report.pdf"
    assert evidence[0]["similarity"] == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_retrieval_fallback_without_reranker(monkeypatch, mock_vector_store, mock_llm):
    monkeypatch.setattr(retrieval_module, "_get_reranker", lambda: None)

    retriever = EvidenceRetriever(mock_vector_store, mock_llm, min_rerank_score=0.3)
    evidence = await retriever.retrieve("Revenue was $5M", "lib1", top_k=1)

    assert len(evidence) == 1
    assert evidence[0]["source"] == "Report.pdf"
