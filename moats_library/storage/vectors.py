"""ChromaDB vector storage with single collection design."""

import chromadb
from chromadb.config import Settings as ChromaSettings
import httpx
from typing import Any
import json

from moats_library.config import get_settings


class VectorStore:
    """ChromaDB vector store using a single collection with metadata filters."""

    COLLECTION_NAME = "library"

    def __init__(self, persist_path: str | None = None):
        settings = get_settings()
        path = persist_path or str(settings.chromadb_path)

        self.client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "hnsw:search_ef": 50,
                "hnsw:M": 32,
                "hnsw:construction_ef": 200,
            },
        )
        self.settings = settings
        self._embedding_cache: dict[str, list[float]] = {}

    async def get_embedding(self, text: str) -> list[float]:
        """Get embedding from OpenRouter (single text)."""
        # Check cache
        cache_key = text[:100]
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": self.settings.app_url,
                    "X-Title": self.settings.app_name,
                },
                json={
                    "model": self.settings.embedding_model,
                    "input": text,
                },
            )
            response.raise_for_status()
            data = response.json()
            embedding = data["data"][0]["embedding"]

            # Cache result
            self._embedding_cache[cache_key] = embedding
            return embedding

    async def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts in a single API call."""
        if not texts:
            return []

        # Check cache for all texts
        results = [None] * len(texts)
        uncached_indices = []
        uncached_texts = []

        for i, text in enumerate(texts):
            cache_key = text[:100]
            if cache_key in self._embedding_cache:
                results[i] = self._embedding_cache[cache_key]
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # If all cached, return early
        if not uncached_texts:
            return results

        # Batch API call for uncached texts
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": self.settings.app_url,
                    "X-Title": self.settings.app_name,
                },
                json={
                    "model": self.settings.embedding_model,
                    "input": uncached_texts,
                },
            )
            response.raise_for_status()
            data = response.json()

            # Map results back and cache
            for j, item in enumerate(data["data"]):
                embedding = item["embedding"]
                original_index = uncached_indices[j]
                results[original_index] = embedding

                # Cache the result
                cache_key = uncached_texts[j][:100]
                self._embedding_cache[cache_key] = embedding

        return results

    async def add_chunks(
        self,
        chunks: list[dict],
        document_id: int,
        document_title: str,
        source_type: str,
        progress_callback=None,
        batch_size: int = 100,
    ) -> list[str]:
        """
        Add document chunks to the vector store using batch embedding.

        Returns list of embedding IDs.
        """
        if not chunks:
            return []

        ids = []
        documents = []
        metadatas = []
        total_chunks = len(chunks)

        # Prepare all metadata first
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
            metadatas.append(metadata)

        # Get embeddings in batches
        all_embeddings = []
        for batch_start in range(0, total_chunks, batch_size):
            batch_end = min(batch_start + batch_size, total_chunks)
            batch_texts = documents[batch_start:batch_end]

            # Batch embedding call
            batch_embeddings = await self.get_embeddings_batch(batch_texts)
            all_embeddings.extend(batch_embeddings)

            # Report progress after each batch
            if progress_callback:
                await progress_callback(batch_end, total_chunks)

        self.collection.upsert(
            ids=ids,
            embeddings=all_embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        return ids

    async def search(
        self,
        query: str,
        n_results: int = 10,
        source_types: list[str] | None = None,
        document_ids: list[int] | None = None,
    ) -> list[dict]:
        """
        Search for similar chunks.

        Args:
            query: Search query
            n_results: Number of results
            source_types: Filter by source types (e.g., ['pdf', 'epub'])
            document_ids: Filter by specific document IDs

        Returns:
            List of matching chunks with metadata and similarity scores
        """
        query_embedding = await self.get_embedding(query)

        where_filter = None
        if source_types or document_ids:
            conditions = []
            if source_types:
                conditions.append({"source_type": {"$in": source_types}})
            if document_ids:
                conditions.append({"document_id": {"$in": document_ids}})

            if len(conditions) == 1:
                where_filter = conditions[0]
            else:
                where_filter = {"$and": conditions}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        # Format results
        formatted = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                formatted.append({
                    "id": chunk_id,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                    "similarity": 1 - results["distances"][0][i],  # cosine distance to similarity
                })

        return formatted

    def get_collection_stats(self) -> dict:
        """Get collection statistics."""
        return {
            "name": self.COLLECTION_NAME,
            "count": self.collection.count(),
        }

    def delete_document_chunks(self, document_id: int) -> None:
        """Delete all chunks for a document."""
        # Get all chunk IDs for this document
        results = self.collection.get(
            where={"document_id": document_id},
            include=[],
        )
        if results["ids"]:
            self.collection.delete(ids=results["ids"])
