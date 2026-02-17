"""ChromaDB vector storage with per-library collections."""

import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import Any

from backend.config import settings


class VectorStore:
    """ChromaDB vector store with library-scoped collections."""

    def __init__(self, persist_path: str | None = None):
        path = persist_path or settings.CHROMADB_PATH
        self.client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def get_collection(self, library_id: str):
        """Get or create a collection for a library."""
        return self.client.get_or_create_collection(
            name=f"library_{library_id}",
            metadata={
                "hnsw:space": "cosine",
                "hnsw:search_ef": 50,
                "hnsw:M": 32,
                "hnsw:construction_ef": 200,
            },
        )

    def add_chunks(
        self,
        library_id: str,
        chunks: list[dict],
        embeddings: list[list[float]],
        document_id: int,
        document_title: str,
        source_type: str,
    ) -> list[str]:
        """Add embedded chunks to the collection. Returns list of chunk IDs."""
        if not chunks or not embeddings:
            return []

        collection = self.get_collection(library_id)
        ids = []
        documents = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"doc_{document_id}_chunk_{i}"
            ids.append(chunk_id)
            documents.append(chunk["text"])
            metadata = {
                "document_id": document_id,
                "document_title": document_title,
                "source_type": source_type,
                "chunk_index": i,
            }
            if chunk.get("start_page"):
                metadata["start_page"] = chunk["start_page"]
            if chunk.get("end_page"):
                metadata["end_page"] = chunk["end_page"]
            if chunk.get("paragraph"):
                metadata["paragraph"] = chunk["paragraph"]
            metadatas.append(metadata)

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        return ids

    def search(
        self,
        library_id: str,
        query_embedding: list[float],
        n_results: int = 10,
        where_filter: dict | None = None,
    ) -> list[dict]:
        """Search for similar chunks."""
        collection = self.get_collection(library_id)

        if collection.count() == 0:
            return []

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, collection.count()),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        formatted = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                formatted.append({
                    "id": chunk_id,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                    "similarity": 1 - results["distances"][0][i],
                })
        return formatted

    def get_stats(self, library_id: str) -> dict:
        collection = self.get_collection(library_id)
        return {"count": collection.count()}

    def delete_document(self, library_id: str, document_id: int) -> None:
        collection = self.get_collection(library_id)
        results = collection.get(where={"document_id": document_id}, include=[])
        if results["ids"]:
            collection.delete(ids=results["ids"])

    def delete_collection(self, library_id: str) -> None:
        try:
            self.client.delete_collection(f"library_{library_id}")
        except Exception:
            pass
