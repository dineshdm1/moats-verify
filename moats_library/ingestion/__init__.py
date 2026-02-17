"""Document ingestion pipeline."""

from moats_library.ingestion.processor import (
    ingest_file,
    ingest_folder,
    ingest_link,
    extract_text,
    SUPPORTED_EXTENSIONS,
)
from moats_library.ingestion.chunker import chunk_text, chunk_by_paragraphs

__all__ = [
    "ingest_file",
    "ingest_folder",
    "ingest_link",
    "extract_text",
    "chunk_text",
    "chunk_by_paragraphs",
    "SUPPORTED_EXTENSIONS",
]
