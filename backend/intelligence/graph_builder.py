"""Build the verification graph from extracted entities."""

import logging
import uuid
from typing import Callable

from backend.intelligence.entity_extractor import extract_entities, ExtractionResult
from backend.storage.neo4j import GraphStore
from backend.storage.chromadb import VectorStore
from backend.storage.sqlite import MetadataDB
from backend.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


async def build_graph_for_library(
    library_id: str,
    db: MetadataDB,
    vector_store: VectorStore,
    graph_store: GraphStore,
    llm: LLMProvider,
    progress_callback: Callable | None = None,
) -> dict:
    """Build the verification graph for an entire library."""
    documents = db.get_documents(library_id)
    if not documents:
        return {"status": "empty", "message": "No documents to process"}

    total_entities = 0
    total_relationships = 0
    processed = 0

    for doc in documents:
        try:
            # Add document node
            await graph_store.add_document(
                doc_id=doc.id, title=doc.title,
                source_type=doc.source_type, library_id=library_id,
            )

            # Get chunks for this document from ChromaDB
            collection = vector_store.get_collection(library_id)
            results = collection.get(
                where={"document_id": doc.id},
                include=["documents", "metadatas"],
            )

            if not results["documents"]:
                continue

            # Process chunks in batches
            chunk_texts = results["documents"]
            for i in range(0, len(chunk_texts), 3):
                batch_text = "\n\n".join(chunk_texts[i:i + 3])
                extraction = await extract_entities(batch_text, llm)

                # Add entities to graph
                for entity in extraction.entities:
                    await graph_store.add_entity(
                        name=entity.name,
                        entity_type=entity.entity_type,
                        properties={"description": entity.description},
                    )
                    await graph_store.link_entity_to_document(
                        entity_name=entity.name,
                        doc_id=doc.id,
                        page=results["metadatas"][i].get("start_page") if results["metadatas"] else None,
                    )
                    total_entities += 1

                # Add relationships
                for rel in extraction.relationships:
                    await graph_store.add_entity_relationship(
                        from_entity=rel.from_entity,
                        to_entity=rel.to_entity,
                        rel_type=rel.rel_type,
                    )
                    total_relationships += 1

                # Add evidence nodes for key chunks
                evidence_id = str(uuid.uuid4())[:8]
                meta = results["metadatas"][i] if results["metadatas"] else {}
                await graph_store.add_evidence(
                    evidence_id=evidence_id,
                    text=chunk_texts[i][:500],
                    doc_id=doc.id,
                    page=meta.get("start_page"),
                    paragraph=meta.get("paragraph"),
                )

            processed += 1
            if progress_callback:
                await progress_callback(processed, len(documents), doc.title)

        except Exception as e:
            logger.error(f"Failed to process document {doc.title}: {e}")
            continue

    return {
        "status": "completed",
        "documents_processed": processed,
        "entities_extracted": total_entities,
        "relationships_created": total_relationships,
    }
