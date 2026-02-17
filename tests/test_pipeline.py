"""Tests for the core verification pipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock

import backend.core.retrieval as retrieval_module
from backend.core.pipeline import VerificationPipeline
from backend.core.verdict import ClaimVerdict, Verdict


@pytest.fixture
def mock_vector_store():
    store = MagicMock()
    store.search.return_value = [
        {
            "text": "Revenue was $5.0M in Q3 2024.",
            "metadata": {"document_id": 1, "document_title": "Report.pdf", "start_page": 12},
            "similarity": 0.9,
        }
    ]
    return store


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.embed_single.return_value = [0.1] * 8
    llm.chat.return_value = "VERDICT: SUPPORTED\nCONFIDENCE: 0.8\nREASON: Fallback"
    return llm


def test_trust_score_all_supported():
    pipeline = VerificationPipeline(llm_provider=AsyncMock(), vector_store=MagicMock())
    verdicts = [
        ClaimVerdict(
            claim_text="A",
            verdict=Verdict.SUPPORTED,
            confidence=0.9,
            evidence_text="",
            evidence_source="",
            evidence_page=None,
            reason="",
            used_llm=False,
        ),
        ClaimVerdict(
            claim_text="B",
            verdict=Verdict.SUPPORTED,
            confidence=0.95,
            evidence_text="",
            evidence_source="",
            evidence_page=None,
            reason="",
            used_llm=False,
        ),
    ]

    score = pipeline._calculate_trust_score(verdicts)
    assert score == 1.0


def test_trust_score_mixed():
    pipeline = VerificationPipeline(llm_provider=AsyncMock(), vector_store=MagicMock())
    verdicts = [
        ClaimVerdict(
            claim_text="A",
            verdict=Verdict.SUPPORTED,
            confidence=1.0,
            evidence_text="",
            evidence_source="",
            evidence_page=None,
            reason="",
            used_llm=False,
        ),
        ClaimVerdict(
            claim_text="B",
            verdict=Verdict.CONTRADICTED,
            confidence=1.0,
            evidence_text="",
            evidence_source="",
            evidence_page=None,
            reason="",
            used_llm=False,
            contradiction_type="magnitude",
        ),
    ]

    score = pipeline._calculate_trust_score(verdicts)
    assert score == 0.5


@pytest.mark.asyncio
async def test_full_pipeline_structured_match(monkeypatch, mock_vector_store, mock_llm):
    monkeypatch.setattr(retrieval_module, "_get_reranker", lambda: None)

    pipeline = VerificationPipeline(llm_provider=mock_llm, vector_store=mock_vector_store)
    result = await pipeline.verify("Revenue was $5M in Q3 2024.", "lib1")

    assert result.total_claims == 1
    assert result.supported_count == 1
    assert result.no_evidence_count == 0
    assert result.claims[0].used_llm is False


@pytest.mark.asyncio
async def test_pipeline_no_evidence_when_low_rerank(monkeypatch, mock_vector_store, mock_llm):
    class _LowRanker:
        def rerank(self, request):
            return [{"meta": {"index": 0}, "score": 0.12}]

    monkeypatch.setattr(retrieval_module, "_get_reranker", lambda: _LowRanker())

    pipeline = VerificationPipeline(llm_provider=mock_llm, vector_store=mock_vector_store)
    result = await pipeline.verify("Revenue was $5M in Q3 2024.", "lib1")

    assert result.total_claims == 1
    assert result.no_evidence_count == 1
    assert result.claims[0].verdict == Verdict.NO_EVIDENCE
