"""Connector for local vector stores (ChromaDB, local Qdrant)."""

from backend.connectors.base import BaseConnector, Chunk
from backend.storage.chromadb import VectorStore
from backend.llm.provider import LLMProvider


class LocalVectorConnector(BaseConnector):
    """Connector for users who already have local vector stores."""

    def __init__(self, vector_store: VectorStore, llm: LLMProvider, library_id: str):
        self.vector_store = vector_store
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
                metadata=r["metadata"],
            )
            for r in results
        ]

    async def get_all_chunks(self) -> list[Chunk]:
        collection = self.vector_store.get_collection(self.library_id)
        if collection.count() == 0:
            return []
        results = collection.get(include=["documents", "metadatas"])
        return [
            Chunk(text=results["documents"][i],
                  metadata=results["metadatas"][i] if results["metadatas"] else {})
            for i in range(len(results["documents"]))
        ]

    def has_semantic_layer(self) -> bool:
        return True

    def has_graph(self) -> bool:
        return False
