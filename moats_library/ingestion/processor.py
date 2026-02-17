"""Document processing and ingestion."""

import hashlib
import os
from pathlib import Path
from typing import AsyncIterator
import asyncio
import httpx

from moats_library.config import get_settings
from moats_library.ingestion.chunker import chunk_text, chunk_by_paragraphs
from moats_library.storage.sqlite import LibraryDB
from moats_library.storage.vectors import VectorStore


# Supported file extensions
SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".epub": "epub",
    ".docx": "docx",
    ".doc": "docx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
}


async def extract_text_from_pdf(file_path: Path) -> tuple[str, list[int]]:
    """Extract text from PDF using pymupdf."""
    import fitz  # pymupdf
    import logging

    text_parts = []
    page_breaks = []
    current_pos = 0

    try:
        doc = fitz.open(file_path)
    except Exception as e:
        logging.error(f"Failed to open PDF {file_path}: {e}")
        raise ValueError(f"Cannot open PDF: {e}")

    if doc.is_encrypted:
        doc.close()
        raise ValueError("PDF is password-protected")

    for page in doc:
        page_text = page.get_text()
        text_parts.append(page_text)
        current_pos += len(page_text)
        page_breaks.append(current_pos)

    doc.close()

    # Check if we got any text (might be image-only PDF)
    full_text = "\n".join(text_parts)
    if not full_text.strip():
        raise ValueError("PDF contains no extractable text (may be image-only)")

    return full_text, page_breaks


async def extract_text_from_epub(file_path: Path) -> str:
    """Extract text from EPUB."""
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(str(file_path))
    text_parts = []

    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text_parts.append(soup.get_text())

    return "\n\n".join(text_parts)


async def extract_text_from_docx(file_path: Path) -> str:
    """Extract text from DOCX."""
    import docx

    doc = docx.Document(file_path)
    return "\n\n".join(para.text for para in doc.paragraphs if para.text.strip())


async def extract_text_from_txt(file_path: Path) -> str:
    """Extract text from plain text file."""
    return file_path.read_text(encoding="utf-8", errors="ignore")


async def extract_text(file_path: Path) -> tuple[str, list[int] | None]:
    """
    Extract text from a file based on its extension.

    Returns:
        Tuple of (text, page_breaks) - page_breaks is None for non-paginated formats
    """
    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return await extract_text_from_pdf(file_path)
    elif ext == ".epub":
        text = await extract_text_from_epub(file_path)
        return text, None
    elif ext in (".docx", ".doc"):
        text = await extract_text_from_docx(file_path)
        return text, None
    elif ext in (".txt", ".md", ".markdown"):
        text = await extract_text_from_txt(file_path)
        return text, None
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def ingest_file(
    file_path: Path,
    db: LibraryDB,
    vector_store: VectorStore,
    title: str | None = None,
    progress_callback=None,
) -> dict:
    """
    Ingest a single file into the library.

    Args:
        file_path: Path to the file
        db: SQLite database
        vector_store: Vector store
        title: Optional title override
        progress_callback: Optional async callback for progress updates

    Returns:
        Dict with ingestion results
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {list(SUPPORTED_EXTENSIONS.keys())}")

    source_type = SUPPORTED_EXTENSIONS[ext]
    doc_title = title or file_path.stem

    if progress_callback:
        await progress_callback(f"Extracting text from {file_path.name}...")

    # Extract text
    text, page_breaks = await extract_text(file_path)

    if not text.strip():
        return {"status": "skipped", "reason": "Empty content", "file": str(file_path)}

    # Check for duplicates
    content_hash = compute_content_hash(text)
    if db.document_exists(content_hash):
        return {"status": "skipped", "reason": "Duplicate content", "file": str(file_path)}

    if progress_callback:
        await progress_callback(f"Chunking {doc_title}...")

    # Chunk text
    chunks = chunk_text(text, page_breaks=page_breaks)

    if progress_callback:
        await progress_callback(f"Adding {doc_title} to database...")

    # Add to SQLite
    doc_id = db.add_document(
        title=doc_title,
        source_type=source_type,
        content_hash=content_hash,
        source_path=str(file_path),
        metadata={"pages": len(page_breaks) if page_breaks else None},
    )

    # Add to vector store with progress tracking
    async def embedding_progress(current: int, total: int):
        if progress_callback:
            await progress_callback(f"Embedding {current}/{total} chunks...")

    embedding_ids = await vector_store.add_chunks(
        chunks=chunks,
        document_id=doc_id,
        document_title=doc_title,
        source_type=source_type,
        progress_callback=embedding_progress,
    )

    # Update chunks with embedding IDs
    for i, chunk in enumerate(chunks):
        chunk["embedding_id"] = embedding_ids[i] if i < len(embedding_ids) else None

    # Store chunks in SQLite
    db.add_chunks(doc_id, chunks)

    return {
        "status": "success",
        "file": str(file_path),
        "doc_id": doc_id,
        "title": doc_title,
        "chunks": len(chunks),
        "source_type": source_type,
    }


async def ingest_folder(
    folder_path: Path,
    db: LibraryDB,
    vector_store: VectorStore,
    recursive: bool = True,
    progress_callback=None,
) -> AsyncIterator[dict]:
    """
    Ingest all supported files from a folder.

    Yields progress updates for each file.
    """
    folder_path = Path(folder_path)

    if not folder_path.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    if not folder_path.is_dir():
        raise ValueError(f"Not a directory: {folder_path}")

    # Find all supported files
    if recursive:
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(folder_path.rglob(f"*{ext}"))
    else:
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(folder_path.glob(f"*{ext}"))

    files = sorted(set(files))  # Remove duplicates and sort

    if not files:
        yield {"status": "empty", "message": "No supported files found"}
        return

    yield {"status": "start", "total": len(files), "message": f"Found {len(files)} files to process"}

    success_count = 0
    skip_count = 0
    error_count = 0

    for i, file_path in enumerate(files):
        try:
            result = await ingest_file(
                file_path,
                db,
                vector_store,
                progress_callback=progress_callback,
            )
            result["progress"] = f"{i + 1}/{len(files)}"

            if result["status"] == "success":
                success_count += 1
            else:
                skip_count += 1

            yield result

        except Exception as e:
            error_count += 1
            yield {
                "status": "error",
                "file": str(file_path),
                "error": str(e),
                "progress": f"{i + 1}/{len(files)}",
            }

    yield {
        "status": "complete",
        "total": len(files),
        "success": success_count,
        "skipped": skip_count,
        "errors": error_count,
    }


async def ingest_link(
    url: str,
    db: LibraryDB,
    vector_store: VectorStore,
    title: str | None = None,
    progress_callback=None,
) -> dict:
    """
    Ingest content from a web URL.
    """
    from bs4 import BeautifulSoup

    if progress_callback:
        await progress_callback(f"Fetching {url}...")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

    # Parse HTML
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style elements
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    # Get text
    text = soup.get_text(separator="\n")
    text = "\n".join(line.strip() for line in text.splitlines() if line.strip())

    if not text:
        return {"status": "skipped", "reason": "No content extracted", "url": url}

    # Get title
    doc_title = title
    if not doc_title:
        title_tag = soup.find("title")
        doc_title = title_tag.get_text().strip() if title_tag else url

    # Check for duplicates
    content_hash = compute_content_hash(text)
    if db.document_exists(content_hash):
        return {"status": "skipped", "reason": "Duplicate content", "url": url}

    if progress_callback:
        await progress_callback(f"Processing {doc_title}...")

    # Chunk
    chunks = chunk_by_paragraphs(text)

    # Add to database
    doc_id = db.add_document(
        title=doc_title,
        source_type="link",
        content_hash=content_hash,
        source_url=url,
        metadata={"url": url},
    )

    if progress_callback:
        await progress_callback(f"Generating embeddings for {len(chunks)} chunks...")

    # Add to vector store
    embedding_ids = await vector_store.add_chunks(
        chunks=chunks,
        document_id=doc_id,
        document_title=doc_title,
        source_type="link",
    )

    for i, chunk in enumerate(chunks):
        chunk["embedding_id"] = embedding_ids[i] if i < len(embedding_ids) else None

    db.add_chunks(doc_id, chunks)

    return {
        "status": "success",
        "url": url,
        "doc_id": doc_id,
        "title": doc_title,
        "chunks": len(chunks),
    }
