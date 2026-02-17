"""ChromaDB retrieval + FlashRank reranking."""

from __future__ import annotations

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        try:
            from flashrank import Ranker

            _reranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")
        except (ImportError, Exception) as exc:
            logger.warning("FlashRank not available: %s", exc)
            _reranker = False
    return _reranker if _reranker is not False else None


@dataclass
class EvidencePassage:
    text: str
    source: str
    page: int | None
    similarity: float
    document_id: int | None


class EvidenceRetriever:
    """Retrieve and rerank evidence from ChromaDB."""

    def __init__(
        self,
        vector_store,
        llm_provider,
        *,
        min_rerank_score: float = 0.3,
    ):
        self.vector_store = vector_store
        self.llm = llm_provider
        self.min_rerank_score = min_rerank_score

    async def retrieve(self, query: str, library_id: str, top_k: int = 5) -> list[dict]:
        """Embed query, search Chroma, rerank with FlashRank."""

        try:
            query_embedding = await self.llm.embed_single(query)
        except Exception as exc:
            logger.warning("Embedding failed during retrieval: %s", exc)
            return []

        try:
            raw_results = self.vector_store.search(
                library_id=library_id,
                query_embedding=query_embedding,
                n_results=top_k * 2,
            )
        except Exception as exc:
            logger.warning("Vector search failed: %s", exc)
            return []

        passages: list[EvidencePassage] = []
        for item in raw_results:
            metadata = item.get("metadata", {})
            passages.append(
                EvidencePassage(
                    text=item.get("text", ""),
                    source=metadata.get("document_title", "Unknown"),
                    page=metadata.get("start_page"),
                    similarity=item.get("similarity", 0.0),
                    document_id=metadata.get("document_id"),
                )
            )

        reranked, used_reranker = self._rerank(query, passages, top_k=top_k)

        # If cross-encoder says the best match is weak, treat as no evidence.
        if used_reranker and reranked and reranked[0].similarity < self.min_rerank_score:
            return []

        return [
            {
                "text": item.text,
                "source": item.source,
                "page": item.page,
                "similarity": item.similarity,
                "document_id": item.document_id,
            }
            for item in reranked
        ]

    def _rerank(
        self, query: str, passages: list[EvidencePassage], top_k: int
    ) -> tuple[list[EvidencePassage], bool]:
        ranker = _get_reranker()
        if not ranker:
            return sorted(passages, key=lambda p: p.similarity, reverse=True)[:top_k], False

        try:
            from flashrank import RerankRequest

            flashrank_passages = [
                {"id": idx, "text": passage.text, "meta": {"index": idx}}
                for idx, passage in enumerate(passages)
            ]
            reranked = ranker.rerank(RerankRequest(query=query, passages=flashrank_passages))

            results: list[EvidencePassage] = []
            for item in reranked[:top_k]:
                idx = item["meta"]["index"]
                passage = passages[idx]
                passage.similarity = item["score"]
                results.append(passage)
            return results, True
        except Exception as exc:
            logger.warning("Reranking failed: %s", exc)
            return sorted(passages, key=lambda p: p.similarity, reverse=True)[:top_k], False
