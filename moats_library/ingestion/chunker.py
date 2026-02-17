"""Text chunking for document ingestion."""

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    """A text chunk with metadata."""

    text: str
    start_page: int | None = None
    end_page: int | None = None
    start_char: int = 0
    end_char: int = 0


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    page_breaks: list[int] | None = None,
) -> list[dict]:
    """
    Split text into overlapping chunks.

    Args:
        text: Full document text
        chunk_size: Target chunk size in characters
        chunk_overlap: Overlap between chunks
        page_breaks: Character positions where pages break

    Returns:
        List of chunk dictionaries with text and metadata
    """
    if not text or not text.strip():
        return []

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) <= chunk_size:
        return [{"text": text, "start_page": 1, "end_page": 1}]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # Try to break at sentence boundary
        if end < len(text):
            # Look for sentence endings within the last 20% of chunk
            search_start = start + int(chunk_size * 0.8)
            search_text = text[search_start:end]

            # Find last sentence boundary
            for sep in ['. ', '? ', '! ', '\n\n', '\n']:
                last_sep = search_text.rfind(sep)
                if last_sep != -1:
                    end = search_start + last_sep + len(sep)
                    break

        chunk_text_content = text[start:end].strip()

        if chunk_text_content:
            # Determine page numbers if page breaks provided
            start_page = None
            end_page = None
            if page_breaks:
                for i, pb in enumerate(page_breaks):
                    if pb <= start:
                        start_page = i + 1
                    if pb <= end:
                        end_page = i + 1

            chunks.append({
                "text": chunk_text_content,
                "start_page": start_page,
                "end_page": end_page,
            })

        # Move to next chunk with overlap
        start = end - chunk_overlap
        if start >= len(text) - chunk_overlap:
            break

    return chunks


def chunk_by_paragraphs(
    text: str,
    max_chunk_size: int = 1500,
    min_chunk_size: int = 200,
) -> list[dict]:
    """
    Split text into chunks by paragraph boundaries.

    Combines small paragraphs and splits large ones.
    """
    if not text or not text.strip():
        return []

    # Split by double newlines (paragraphs)
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        # If paragraph alone is too big, split it
        if len(para) > max_chunk_size:
            # Save current accumulated chunk
            if current_chunk:
                chunks.append({"text": current_chunk})
                current_chunk = ""

            # Split large paragraph
            sub_chunks = chunk_text(para, chunk_size=max_chunk_size, chunk_overlap=100)
            chunks.extend(sub_chunks)
            continue

        # Try to add to current chunk
        test_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para

        if len(test_chunk) > max_chunk_size:
            # Save current and start new
            if current_chunk:
                chunks.append({"text": current_chunk})
            current_chunk = para
        else:
            current_chunk = test_chunk

    # Add remaining
    if current_chunk:
        chunks.append({"text": current_chunk})

    return chunks
