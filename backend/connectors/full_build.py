"""Full build connector — builds everything from raw documents."""

from pathlib import Path

from backend.connectors.base import BaseConnector, Chunk
from backend.storage.chromadb import VectorStore
from backend.storage.neo4j import GraphStore
from backend.llm.provider import LLMProvider


class FullBuildConnector(BaseConnector):
    """Connector for users who start from scratch with raw documents."""

    def __init__(self, vector_store: VectorStore, graph_store: GraphStore,
                 llm: LLMProvider, library_id: str):
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.llm = llm
        self.library_id = library_id

    async def get_chunks(self, query: str, top_k: int = 10) -> list[Chunk]:
        query_embedding = await self.llm.embed_single(query)
        results = self.vector_store.search(
            library_id=self.library_id,
            query_embedding=query_embedding,
            n_results=top_k,
        )
        return [
            Chunk(
                text=r["text"],
                document_id=r["metadata"].get("document_id"),
                document_title=r["metadata"].get("document_title", ""),
                source_type=r["metadata"].get("source_type", ""),
                page=r["metadata"].get("start_page"),
                paragraph=r["metadata"].get("paragraph"),
                metadata=r["metadata"],
            )
            for r in results
        ]

    async def get_all_chunks(self) -> list[Chunk]:
        collection = self.vector_store.get_collection(self.library_id)
        if collection.count() == 0:
            return []
        results = collection.get(include=["documents", "metadatas"])
        chunks = []
        for i, text in enumerate(results["documents"]):
            meta = results["metadatas"][i] if results["metadatas"] else {}
            chunks.append(Chunk(
                text=text,
                document_id=meta.get("document_id"),
                document_title=meta.get("document_title", ""),
                source_type=meta.get("source_type", ""),
                page=meta.get("start_page"),
                paragraph=meta.get("paragraph"),
                metadata=meta,
            ))
        return chunks

    def has_semantic_layer(self) -> bool:
        return True

    def has_graph(self) -> bool:
        return True
