"""Neo4j graph storage with verification-specific schema."""

import re
from neo4j import AsyncGraphDatabase
from typing import Any

from backend.config import settings

_SAFE_REL_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{0,49}$')


def _sanitize_rel(rel_type: str) -> str:
    sanitized = rel_type.upper().replace(' ', '_').replace('-', '_')
    sanitized = re.sub(r'[^A-Z0-9_]', '', sanitized)
    if not sanitized:
        return "RELATES_TO"
    if not sanitized[0].isalpha():
        sanitized = "REL_" + sanitized
    return sanitized[:50]


class GraphStore:
    """Neo4j graph with verification-specific schema."""

    DATABASE = "neo4j"

    def __init__(self):
        self.driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        self._initialized = False

    async def init(self) -> None:
        if self._initialized:
            return
        async with self.driver.session(database=self.DATABASE) as session:
            async def create_schema(tx):
                # Core nodes
                await tx.run("CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE")
                await tx.run("CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:Evidence) REQUIRE e.id IS UNIQUE")
                await tx.run("CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")
                await tx.run("CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE")
                # Indexes
                await tx.run("CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)")
                await tx.run("CREATE INDEX claim_type IF NOT EXISTS FOR (c:Claim) ON (c.type)")
            await session.execute_write(create_schema)
        self._initialized = True

    async def close(self) -> None:
        await self.driver.close()

    # ── Document & Entity nodes ──

    async def add_document(self, doc_id: int, title: str, source_type: str,
                           library_id: str) -> None:
        await self.init()
        async def _write(tx):
            await tx.run(
                """MERGE (d:Document {doc_id: $doc_id})
                   SET d.title = $title, d.source_type = $source_type, d.library_id = $library_id""",
                doc_id=doc_id, title=title, source_type=source_type, library_id=library_id,
            )
        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    async def add_entity(self, name: str, entity_type: str, properties: dict | None = None) -> None:
        await self.init()
        props = properties or {}
        async def _write(tx):
            await tx.run(
                """MERGE (e:Entity {name: $name})
                   SET e.type = $type, e += $props""",
                name=name.lower(), type=entity_type, props=props,
            )
        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    async def add_entity_relationship(self, from_entity: str, to_entity: str,
                                       rel_type: str, properties: dict | None = None) -> None:
        await self.init()
        safe_rel = _sanitize_rel(rel_type)
        props = properties or {}
        async def _write(tx):
            await tx.run(
                f"""MATCH (e1:Entity {{name: $from_name}})
                    MATCH (e2:Entity {{name: $to_name}})
                    MERGE (e1)-[r:{safe_rel}]->(e2)
                    SET r += $props""",
                from_name=from_entity.lower(), to_name=to_entity.lower(), props=props,
            )
        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    async def link_entity_to_document(self, entity_name: str, doc_id: int,
                                       page: int | None = None, paragraph: int | None = None) -> None:
        await self.init()
        props = {}
        if page:
            props["page"] = page
        if paragraph:
            props["paragraph"] = paragraph
        async def _write(tx):
            await tx.run(
                """MATCH (e:Entity {name: $name})
                   MATCH (d:Document {doc_id: $doc_id})
                   MERGE (d)-[r:MENTIONS]->(e)
                   SET r += $props""",
                name=entity_name.lower(), doc_id=doc_id, props=props,
            )
        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    # ── Verification-specific: Evidence & temporal state ──

    async def add_evidence(self, evidence_id: str, text: str, doc_id: int,
                           page: int | None = None, paragraph: int | None = None) -> None:
        await self.init()
        async def _write(tx):
            await tx.run(
                """MERGE (e:Evidence {id: $id})
                   SET e.text = $text, e.page = $page, e.paragraph = $paragraph
                   WITH e
                   MATCH (d:Document {doc_id: $doc_id})
                   MERGE (e)-[:SOURCED_FROM]->(d)""",
                id=evidence_id, text=text, doc_id=doc_id, page=page, paragraph=paragraph,
            )
        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    async def set_temporal_state(self, entity_name: str, attribute: str,
                                  value: str, as_of: str) -> None:
        """Track entity state at a point in time."""
        await self.init()
        async def _write(tx):
            await tx.run(
                """MATCH (e:Entity {name: $name})
                   MERGE (e)-[r:HAS_STATE {attribute: $attr, as_of: $as_of}]->(s:State {value: $value})
                   SET s.as_of = $as_of""",
                name=entity_name.lower(), attr=attribute, value=value, as_of=as_of,
            )
        async with self.driver.session(database=self.DATABASE) as session:
            await session.execute_write(_write)

    # ── Query methods for verification ──

    async def find_entity_evidence(self, entity_name: str, limit: int = 20) -> list[dict]:
        """Find all evidence related to an entity."""
        await self.init()
        async def _read(tx):
            result = await tx.run(
                """MATCH (e:Entity {name: $name})<-[:MENTIONS]-(d:Document)<-[:SOURCED_FROM]-(ev:Evidence)
                   RETURN ev.id as evidence_id, ev.text as text, ev.page as page,
                          d.doc_id as doc_id, d.title as doc_title
                   LIMIT $limit""",
                name=entity_name.lower(), limit=limit,
            )
            return await result.data()
        async with self.driver.session(database=self.DATABASE) as session:
            return await session.execute_read(_read)

    async def find_related_entities(self, entity_name: str, max_depth: int = 2,
                                     limit: int = 20) -> list[dict]:
        await self.init()
        async def _read(tx):
            result = await tx.run(
                f"""MATCH path = (e:Entity {{name: $name}})-[*1..{max_depth}]-(related:Entity)
                    RETURN DISTINCT related.name as name, related.type as type,
                           length(path) as distance
                    ORDER BY distance, related.name
                    LIMIT $limit""",
                name=entity_name.lower(), limit=limit,
            )
            return await result.data()
        async with self.driver.session(database=self.DATABASE) as session:
            return await session.execute_read(_read)

    async def find_documents_by_entity(self, entity_name: str) -> list[dict]:
        await self.init()
        async def _read(tx):
            result = await tx.run(
                """MATCH (d:Document)-[:MENTIONS]->(e:Entity {name: $name})
                   RETURN d.doc_id as doc_id, d.title as title""",
                name=entity_name.lower(),
            )
            return await result.data()
        async with self.driver.session(database=self.DATABASE) as session:
            return await session.execute_read(_read)

    async def get_graph_stats(self, library_id: str | None = None) -> dict:
        await self.init()
        async def _read(tx):
            if library_id:
                node_result = await tx.run(
                    """MATCH (d:Document {library_id: $lib})-[*0..2]-(n)
                       RETURN labels(n)[0] as label, count(DISTINCT n) as count""",
                    lib=library_id,
                )
            else:
                node_result = await tx.run(
                    "MATCH (n) RETURN labels(n)[0] as label, count(*) as count"
                )
            records = await node_result.data()
            by_label = {r["label"]: r["count"] for r in records}
            rel_result = await tx.run("MATCH ()-[r]->() RETURN count(r) as total")
            rel_data = await rel_result.single()
            return {"nodes": by_label, "relationships": rel_data["total"] if rel_data else 0}
        async with self.driver.session(database=self.DATABASE) as session:
            return await session.execute_read(_read)
