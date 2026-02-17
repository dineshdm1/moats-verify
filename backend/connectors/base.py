"""Abstract connector interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Chunk:
    text: str
    document_id: int | None = None
    document_title: str = ""
    source_type: str = ""
    page: int | None = None
    paragraph: int | None = None
    metadata: dict | None = None


@dataclass
class Node:
    name: str
    node_type: str
    properties: dict | None = None


@dataclass
class Relationship:
    from_node: str
    to_node: str
    rel_type: str
    properties: dict | None = None


class BaseConnector(ABC):
    """Abstract connector interface for data sources."""

    @abstractmethod
    async def get_chunks(self, query: str, top_k: int = 10) -> list[Chunk]:
        """Retrieve relevant chunks for a query."""
        ...

    @abstractmethod
    async def get_all_chunks(self) -> list[Chunk]:
        """Get all chunks (for graph building)."""
        ...

    @abstractmethod
    def has_semantic_layer(self) -> bool:
        """Whether this connector has vector embeddings."""
        ...

    @abstractmethod
    def has_graph(self) -> bool:
        """Whether this connector has a graph database."""
        ...

    async def get_graph_nodes(self, entities: list[str]) -> list[Node]:
        """Get graph nodes for entities. Override if graph is available."""
        return []

    async def get_relationships(self, node: str) -> list[Relationship]:
        """Get relationships for a node. Override if graph is available."""
        return []
