"""Dual retrieval — semantic search + graph traversal."""

import logging
from dataclasses import dataclass

from backend.deprecated.verify.claim_extractor import Claim
from backend.storage.chromadb import VectorStore
from backend.storage.neo4j import GraphStore
from backend.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class EvidenceChunk:
    text: str
    document_id: int | None
    document_title: str
    page: int | None
    paragraph: int | None
    similarity: float
    source: str  # "semantic" or "graph"


async def retrieve_evidence(
    claim: Claim,
    library_id: str,
    vector_store: VectorStore,
    graph_store: GraphStore | None,
    llm: LLMProvider,
    top_k: int = 10,
) -> list[EvidenceChunk]:
    """Dual retrieval: combine semantic search + graph traversal results."""
    evidence = []

    # Path A: Semantic search
    try:
        query_embedding = await llm.embed_single(claim.text)
        semantic_results = vector_store.search(
            library_id=library_id,
            query_embedding=query_embedding,
            n_results=top_k * 2,  # Over-fetch for reranking
        )
        for r in semantic_results:
            evidence.append(EvidenceChunk(
                text=r["text"],
                document_id=r["metadata"].get("document_id"),
                document_title=r["metadata"].get("document_title", "Unknown"),
                page=r["metadata"].get("start_page"),
                paragraph=r["metadata"].get("paragraph"),
                similarity=r["similarity"],
                source="semantic",
            ))
    except Exception as e:
        logger.warning(f"Semantic search failed for claim: {e}")

    # Path B: Graph traversal (if available and entities extracted)
    if graph_store and claim.entities:
        try:
            for entity in claim.entities[:3]:  # Limit entity lookups
                # Find evidence linked to this entity
                entity_evidence = await graph_store.find_entity_evidence(entity)
                for ev in entity_evidence:
                    # Avoid duplicates
                    if not any(e.text == ev["text"] for e in evidence):
                        evidence.append(EvidenceChunk(
                            text=ev["text"],
                            document_id=ev["doc_id"],
                            document_title=ev.get("doc_title", "Unknown"),
                            page=ev.get("page"),
                            paragraph=None,
                            similarity=0.5,  # Default score for graph results
                            source="graph",
                        ))

                # Also find related entities for broader context
                related = await graph_store.find_related_entities(entity, max_depth=1, limit=5)
                for rel in related:
                    rel_evidence = await graph_store.find_entity_evidence(rel["name"])
                    for ev in rel_evidence[:2]:  # Limit per related entity
                        if not any(e.text == ev["text"] for e in evidence):
                            evidence.append(EvidenceChunk(
                                text=ev["text"],
                                document_id=ev["doc_id"],
                                document_title=ev.get("doc_title", "Unknown"),
                                page=ev.get("page"),
                                paragraph=None,
                                similarity=0.3,  # Lower score for indirect graph results
                                source="graph",
                            ))
        except Exception as e:
            logger.warning(f"Graph traversal failed: {e}")

    return evidence
