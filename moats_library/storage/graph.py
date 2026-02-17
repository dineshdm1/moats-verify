"""Neo4j graph storage for concepts and relationships."""

import re
from neo4j import AsyncGraphDatabase
from typing import Any
import asyncio

from moats_library.config import get_settings

# Whitelist pattern for relationship types — only alphanumeric and underscores
_SAFE_REL_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{0,49}$')

# Known relationship types used in the graph
_KNOWN_REL_TYPES = frozenset({
    "AUTHORED", "COVERS", "MENTIONS", "RELATES_TO", "PROPOSED_BY",
    "DERIVED_FROM", "CONTRADICTS", "SUPPORTS", "PART_OF", "EXAMPLE_OF",
    "INFLUENCES", "DEPENDS_ON", "PRECEDES", "FOLLOWS", "CAUSES",
    "ENABLES", "IMPLEMENTS", "EXTENDS", "USES", "APPLIED_TO",
})


def _sanitize_relationship_type(rel_type: str) -> str:
    """Sanitize a relationship type string to prevent Cypher injection."""
    sanitized = rel_type.upper().replace(' ', '_').replace('-', '_')
    # Strip anything that isn't alphanumeric or underscore
    sanitized = re.sub(r'[^A-Z0-9_]', '', sanitized)
    if not sanitized:
        return "RELATES_TO"
    # Ensure it starts with a letter
    if not sanitized[0].isalpha():
        sanitized = "REL_" + sanitized
    # Truncate to 50 chars
    return sanitized[:50]


class GraphStore:
    """Neo4j graph database for concept relationships."""

    DATABASE = "neo4j"

    def __init__(self):
        settings = get_settings()
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        self._initialized = False

    async def init(self) -> None:
        """Initialize graph schema with constraints and indexes."""
        if self._initialized:
            return

        async with self.driver.session(database=self.DATABASE) as session:
            # Schema DDL uses execute_write
            async def create_schema(tx):
                await tx.run("""
                    CREATE CONSTRAINT concept_name IF NOT EXISTS
                    FOR (c:Concept) REQUIRE c.name IS UNIQUE
                """)
                await tx.run("""
                    CREATE CONSTRAINT author_name IF NOT EXISTS
                    FOR (a:Author) REQUIRE a.name IS UNIQUE
                """)
                await tx.run("""
                    CREATE CONSTRAINT topic_name IF NOT EXISTS
                    FOR (t:Topic) REQUIRE t.name IS UNIQUE
                """)
                await tx.run("""
                    CREATE CONSTRAINT document_id IF NOT EXISTS
                    FOR (d:Document) REQUIRE d.doc_id IS UNIQUE
                """)
                await tx.run("""
                    CREATE INDEX concept_type IF NOT EXISTS FOR (c:Concept) ON (c.type)
                """)

            await session.execute_write(create_schema)

        self._initialized = True

    async def close(self) -> None:
        """Close the driver connection."""
        await self.driver.close()

    async def add_document(
        self,
        doc_id: int,
        title: str,
        source_type: str,
        authors: list[str] | None = None,
        topics: list[str] | None = None,
    ) -> None:
        """Add a document node with relationships."""
        await self.init()

        async def _write(tx):
            # Create document node
            await tx.run(
                """
                MERGE (d:Document {doc_id: $doc_id})
                SET d.title = $title, d.source_type = $source_type
                """,
                doc_id=doc_id,
                title=title,
                source_type=source_type,
            )

            # Add author relationships
            if authors:
                for author in authors:
                    await tx.run(
                        """
                        MERGE (a:Author {name: $name})
                        WITH a
                        MATCH (d:Document {doc_id: $doc_id})
                        MERGE (a)-[:AUTHORED]->(d)
                        """,
                        name=author,
                        doc_id=doc_id,
                    )

            # Add topic relationships
            if topics:
                for topic in topics:
                    await tx.run(
                        """
                        MERGE (t:Topic {name: $name})
                        WITH t
                        MATCH (d:Document {doc_id: $doc_id})
                        MERGE (d)-[:COVERS]->(t)
                        """,
                        name=topic.lower(),
                        doc_id=doc_id,
                    )

        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    async def add_concept(
        self,
        name: str,
        concept_type: str,
        description: str | None = None,
        source_doc_id: int | None = None,
    ) -> None:
        """Add a concept node."""
        await self.init()

        async def _write(tx):
            await tx.run(
                """
                MERGE (c:Concept {name: $name})
                SET c.type = $type, c.description = $description
                """,
                name=name.lower(),
                type=concept_type,
                description=description,
            )

            if source_doc_id:
                await tx.run(
                    """
                    MATCH (c:Concept {name: $name})
                    MATCH (d:Document {doc_id: $doc_id})
                    MERGE (d)-[:MENTIONS]->(c)
                    """,
                    name=name.lower(),
                    doc_id=source_doc_id,
                )

        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    async def add_concept_relationship(
        self,
        from_concept: str,
        to_concept: str,
        relationship: str,
        properties: dict | None = None,
    ) -> None:
        """Add a relationship between concepts."""
        await self.init()

        props = properties or {}
        safe_rel = _sanitize_relationship_type(relationship)

        async def _write(tx):
            query = f"""
                MATCH (c1:Concept {{name: $from_name}})
                MATCH (c2:Concept {{name: $to_name}})
                MERGE (c1)-[r:{safe_rel}]->(c2)
                SET r += $props
            """
            await tx.run(
                query,
                from_name=from_concept.lower(),
                to_name=to_concept.lower(),
                props=props,
            )

        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    async def find_related_concepts(
        self,
        concept_name: str,
        max_depth: int = 2,
        limit: int = 20,
    ) -> list[dict]:
        """Find concepts related to a given concept."""
        await self.init()

        async def _read(tx):
            # Filter to known relationship types to avoid noisy traversals
            result = await tx.run(
                f"""
                MATCH path = (c:Concept {{name: $name}})-[:RELATES_TO|PROPOSED_BY|DERIVED_FROM|CONTRADICTS|SUPPORTS|PART_OF|EXAMPLE_OF|INFLUENCES|DEPENDS_ON|CAUSES|ENABLES|IMPLEMENTS|EXTENDS|USES|APPLIED_TO|MENTIONS*1..{max_depth}]-(related)
                WHERE related:Concept
                RETURN DISTINCT related.name as name, related.type as type,
                       related.description as description,
                       length(path) as distance
                ORDER BY distance, related.name
                LIMIT $limit
                """,
                name=concept_name.lower(),
                limit=limit,
            )
            return await result.data()

        async with self.driver.session(database=self.DATABASE) as session:
            return await session.execute_read(_read)

    async def find_documents_by_concept(
        self,
        concept_name: str,
        limit: int = 10,
    ) -> list[dict]:
        """Find documents that mention a concept."""
        await self.init()

        async def _read(tx):
            result = await tx.run(
                """
                MATCH (d:Document)-[:MENTIONS]->(c:Concept {name: $name})
                RETURN d.doc_id as doc_id, d.title as title, d.source_type as source_type
                LIMIT $limit
                """,
                name=concept_name.lower(),
                limit=limit,
            )
            return await result.data()

        async with self.driver.session(database=self.DATABASE) as session:
            return await session.execute_read(_read)

    async def find_author_topics(self, author_name: str) -> list[str]:
        """Find topics an author writes about."""
        await self.init()

        async def _read(tx):
            result = await tx.run(
                """
                MATCH (a:Author {name: $name})-[:AUTHORED]->(d:Document)-[:COVERS]->(t:Topic)
                RETURN DISTINCT t.name as topic
                """,
                name=author_name,
            )
            return await result.data()

        async with self.driver.session(database=self.DATABASE) as session:
            records = await session.execute_read(_read)
            return [r["topic"] for r in records]

    async def get_graph_stats(self) -> dict:
        """Get graph statistics."""
        await self.init()

        async def _read(tx):
            result = await tx.run(
                """
                MATCH (n)
                RETURN labels(n)[0] as label, count(*) as count
                """
            )
            records = await result.data()
            by_label = {r["label"]: r["count"] for r in records}

            rel_result = await tx.run(
                """
                MATCH ()-[r]->()
                RETURN count(r) as relationships
                """
            )
            rel_data = await rel_result.single()

            return {
                "nodes": by_label,
                "relationships": rel_data["relationships"] if rel_data else 0,
            }

        async with self.driver.session(database=self.DATABASE) as session:
            return await session.execute_read(_read)
