"""FlashRank reranking for evidence chunks."""

import logging
from backend.deprecated.verify.dual_retrieval import EvidenceChunk

logger = logging.getLogger(__name__)

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        try:
            from flashrank import Ranker
            _reranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")
        except (ImportError, Exception) as e:
            logger.warning(f"FlashRank not available: {e}")
            _reranker = False
    return _reranker if _reranker is not False else None


def rerank_evidence(query: str, evidence: list[EvidenceChunk], top_k: int = 5) -> list[EvidenceChunk]:
    """Rerank evidence using FlashRank cross-encoder."""
    ranker = _get_reranker()
    if not ranker or len(evidence) <= top_k:
        # Sort by similarity and return
        return sorted(evidence, key=lambda e: e.similarity, reverse=True)[:top_k]

    try:
        from flashrank import RerankRequest
        passages = [{"id": i, "text": e.text, "meta": {"index": i}} for i, e in enumerate(evidence)]
        reranked = ranker.rerank(RerankRequest(query=query, passages=passages))

        result = []
        for item in reranked[:top_k]:
            idx = item["meta"]["index"]
            chunk = evidence[idx]
            chunk.similarity = item["score"]
            result.append(chunk)
        return result

    except Exception as e:
        logger.warning(f"Reranking failed: {e}")
        return sorted(evidence, key=lambda e: e.similarity, reverse=True)[:top_k]
