"""Build and manage concept relationships in Neo4j."""

from moats_library.storage.graph import GraphStore
from moats_library.concepts.extraction import ExtractionResult


async def build_relationships(
    extraction: ExtractionResult,
    document_id: int,
    document_title: str,
    graph_store: GraphStore,
) -> dict:
    """
    Build graph relationships from extraction results.

    Args:
        extraction: Extracted concepts and relationships
        document_id: Source document ID
        document_title: Source document title
        graph_store: Neo4j graph store

    Returns:
        Statistics about created nodes and relationships
    """
    stats = {
        "document": 1,
        "concepts": 0,
        "authors": 0,
        "topics": 0,
        "relationships": 0,
    }

    # Add document node
    await graph_store.add_document(
        doc_id=document_id,
        title=document_title,
        source_type="document",
        authors=extraction.authors,
        topics=extraction.topics,
    )

    # Add concepts
    for concept in extraction.concepts:
        await graph_store.add_concept(
            name=concept.name,
            concept_type=concept.type,
            description=concept.description,
            source_doc_id=document_id,
        )
        stats["concepts"] += 1

    # Add relationships between concepts
    for from_concept, rel_type, to_concept in extraction.relationships:
        # Ensure both concepts exist
        await graph_store.add_concept(
            name=from_concept,
            concept_type="concept",
            source_doc_id=document_id,
        )
        await graph_store.add_concept(
            name=to_concept,
            concept_type="concept",
            source_doc_id=document_id,
        )

        await graph_store.add_concept_relationship(
            from_concept=from_concept,
            to_concept=to_concept,
            relationship=rel_type,
        )
        stats["relationships"] += 1

    stats["authors"] = len(extraction.authors)
    stats["topics"] = len(extraction.topics)

    return stats


async def find_concept_connections(
    concept: str,
    graph_store: GraphStore,
    max_depth: int = 2,
) -> dict:
    """
    Find all connections for a concept.

    Returns:
        Dict with related concepts, documents, and authors
    """
    related = await graph_store.find_related_concepts(
        concept_name=concept,
        max_depth=max_depth,
    )

    documents = await graph_store.find_documents_by_concept(
        concept_name=concept,
    )

    return {
        "concept": concept,
        "related_concepts": related,
        "documents": documents,
    }


async def get_knowledge_map(
    graph_store: GraphStore,
    center_concept: str | None = None,
    limit: int = 50,
) -> dict:
    """
    Get a map of concepts and their relationships.

    If center_concept is provided, focuses on that concept's neighborhood.
    Otherwise returns the most connected concepts.
    """
    stats = await graph_store.get_graph_stats()

    if center_concept:
        connections = await find_concept_connections(
            concept=center_concept,
            graph_store=graph_store,
            max_depth=2,
        )
        return {
            "type": "focused",
            "center": center_concept,
            "connections": connections,
            "stats": stats,
        }

    return {
        "type": "overview",
        "stats": stats,
    }
