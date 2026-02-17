"""Tests for connector interface."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from backend.connectors.base import BaseConnector, Chunk
from backend.connectors.local_vectors import LocalVectorConnector


@pytest.fixture
def mock_vector_store():
    vs = MagicMock()
    vs.search.return_value = [
        {
            "id": "chunk1",
            "text": "Test evidence text.",
            "metadata": {
                "document_id": 1,
                "document_title": "Doc.pdf",
                "source_type": "pdf",
                "start_page": 5,
            },
            "distance": 0.15,
            "similarity": 0.85,
        }
    ]
    vs.get_collection.return_value = MagicMock(count=MagicMock(return_value=100))
    return vs


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.embed_single.return_value = [0.1] * 768
    return llm


@pytest.mark.asyncio
async def test_local_vector_connector_search(mock_vector_store, mock_llm):
    connector = LocalVectorConnector(mock_vector_store, mock_llm, "lib1")

    assert connector.has_semantic_layer() is True
    assert connector.has_graph() is False

    chunks = await connector.get_chunks("What is the revenue?", top_k=5)

    assert len(chunks) == 1
    assert chunks[0].text == "Test evidence text."
    assert chunks[0].document_title == "Doc.pdf"
    assert chunks[0].page == 5

    mock_llm.embed_single.assert_called_once_with("What is the revenue?")
    mock_vector_store.search.assert_called_once()


def test_base_connector_is_abstract():
    """Ensure BaseConnector can't be instantiated directly."""
    with pytest.raises(TypeError):
        BaseConnector()
