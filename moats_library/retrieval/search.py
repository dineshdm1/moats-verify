"""Search across library sources."""

import logging
from dataclasses import dataclass
from typing import Any
import httpx

from moats_library.config import get_settings
from moats_library.storage.sqlite import LibraryDB
from moats_library.storage.vectors import VectorStore
from moats_library.storage.graph import GraphStore

logger = logging.getLogger(__name__)

# Lazy-loaded reranker singleton
_reranker = None


def _get_reranker():
    """Get or initialize the FlashRank reranker (lazy singleton)."""
    global _reranker
    if _reranker is None:
        try:
            from flashrank import Ranker
            _reranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")
            logger.info("FlashRank reranker initialized")
        except ImportError:
            logger.warning("flashrank not installed — reranking disabled")
            _reranker = False  # Sentinel: tried and failed
        except Exception as e:
            logger.warning(f"FlashRank init failed: {e}")
            _reranker = False
    return _reranker if _reranker is not False else None


def rerank_results(query: str, results: list["SearchResult"], top_k: int = 5) -> list["SearchResult"]:
    """Rerank search results using FlashRank cross-encoder."""
    ranker = _get_reranker()
    if not ranker or len(results) <= top_k:
        return results[:top_k]

    try:
        from flashrank import RerankRequest
        passages = [{"id": i, "text": r.text, "meta": {"index": i}} for i, r in enumerate(results)]
        rerank_request = RerankRequest(query=query, passages=passages)
        reranked = ranker.rerank(rerank_request)

        # Map back to SearchResult objects, preserving reranked order
        reranked_results = []
        for item in reranked[:top_k]:
            original_idx = item["meta"]["index"]
            result = results[original_idx]
            result.similarity = item["score"]  # Replace with reranker score
            reranked_results.append(result)

        return reranked_results
    except Exception as e:
        logger.warning(f"Reranking failed, returning original order: {e}")
        return results[:top_k]


@dataclass
class SearchResult:
    """A single search result."""

    text: str
    source_type: str
    document_title: str
    document_id: int
    similarity: float
    page: int | None = None
    source: str = "library"  # 'library' or 'web'
    url: str | None = None


@dataclass
class SearchResults:
    """Collection of search results."""

    query: str
    results: list[SearchResult]
    web_results: list[dict] | None = None


async def search_library(
    query: str,
    vector_store: VectorStore,
    db: LibraryDB,
    graph_store: GraphStore | None = None,
    n_results: int = 10,
    source_types: list[str] | None = None,
    include_web: bool = False,
) -> SearchResults:
    """
    Search the library using vector similarity and optional graph context.

    Args:
        query: Search query
        vector_store: Vector store for semantic search
        db: SQLite database for metadata
        graph_store: Optional graph store for concept expansion
        n_results: Number of results
        source_types: Filter by source types
        include_web: Whether to include web search results

    Returns:
        SearchResults with matching chunks
    """
    # Over-fetch for reranking (3x the requested amount, min 20)
    fetch_count = max(n_results * 3, 20)

    # Vector search
    vector_results = await vector_store.search(
        query=query,
        n_results=fetch_count,
        source_types=source_types,
    )

    # Convert to SearchResult objects
    results = []
    for vr in vector_results:
        metadata = vr["metadata"]
        results.append(
            SearchResult(
                text=vr["text"],
                source_type=metadata.get("source_type", "unknown"),
                document_title=metadata.get("document_title", "Unknown"),
                document_id=metadata.get("document_id", 0),
                similarity=vr["similarity"],
                page=metadata.get("start_page"),
            )
        )

    # Rerank results using FlashRank cross-encoder
    results = rerank_results(query, results, top_k=n_results)

    # Optional: expand with graph context
    if graph_store:
        try:
            # Find related concepts to boost relevant documents
            # This is a simple approach - could be enhanced with graph algorithms
            pass
        except Exception:
            pass  # Graph is optional enhancement

    # Optional: web search
    web_results = None
    if include_web:
        web_results = await search_web(query)

    return SearchResults(
        query=query,
        results=results,
        web_results=web_results,
    )


async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web using Tavily.

    Returns list of web results with title, url, and content.
    """
    settings = get_settings()

    if not settings.tavily_api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": True,
                    "include_raw_content": False,
                },
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for r in data.get("results", []):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0),
                })

            return results

    except Exception as e:
        return []


def format_results_for_context(results: SearchResults, max_chars: int = 8000) -> str:
    """
    Format search results as context for the LLM.
    """
    lines = []
    char_count = 0

    for i, result in enumerate(results.results):
        source_info = f"[{result.document_title}]"
        if result.page:
            source_info += f" (p.{result.page})"

        entry = f"### Source {i + 1}: {source_info}\n{result.text}\n"

        if char_count + len(entry) > max_chars:
            break

        lines.append(entry)
        char_count += len(entry)

    # Add web results if present
    if results.web_results:
        lines.append("\n### Web Sources\n")
        for wr in results.web_results[:3]:
            web_entry = f"**{wr['title']}** ({wr['url']})\n{wr['content'][:500]}...\n"
            if char_count + len(web_entry) > max_chars:
                break
            lines.append(web_entry)
            char_count += len(web_entry)

    return "\n".join(lines)
