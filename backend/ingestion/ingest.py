"""Document ingestion — extract, chunk, embed, store."""

import hashlib
from pathlib import Path
from typing import AsyncIterator, Callable

from backend.ingestion.chunker import chunk_text, chunk_by_paragraphs
from backend.storage.sqlite import MetadataDB
from backend.storage.chromadb import VectorStore
from backend.llm.provider import LLMProvider

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf", ".epub": "epub", ".docx": "docx", ".doc": "docx",
    ".txt": "txt", ".md": "md", ".markdown": "md",
}


async def extract_text_from_pdf(file_path: Path) -> tuple[str, list[int]]:
    import fitz
    text_parts, page_breaks = [], []
    current_pos = 0
    doc = fitz.open(file_path)
    if doc.is_encrypted:
        doc.close()
        raise ValueError("PDF is password-protected")
    for page in doc:
        page_text = page.get_text()
        text_parts.append(page_text)
        current_pos += len(page_text)
        page_breaks.append(current_pos)
    doc.close()
    full_text = "\n".join(text_parts)
    if not full_text.strip():
        raise ValueError("PDF contains no extractable text")
    return full_text, page_breaks


async def extract_text_from_epub(file_path: Path) -> str:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    book = epub.read_epub(str(file_path))
    parts = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), "html.parser")
            parts.append(soup.get_text())
    return "\n\n".join(parts)


async def extract_text_from_docx(file_path: Path) -> str:
    import docx
    doc = docx.Document(file_path)
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


async def extract_text(file_path: Path) -> tuple[str, list[int] | None]:
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return await extract_text_from_pdf(file_path)
    elif ext == ".epub":
        return await extract_text_from_epub(file_path), None
    elif ext in (".docx", ".doc"):
        return await extract_text_from_docx(file_path), None
    elif ext in (".txt", ".md", ".markdown"):
        return file_path.read_text(encoding="utf-8", errors="ignore"), None
    raise ValueError(f"Unsupported file type: {ext}")


def compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def ingest_file(
    file_path: Path,
    library_id: str,
    db: MetadataDB,
    vector_store: VectorStore,
    llm: LLMProvider,
    progress_callback: Callable | None = None,
) -> dict:
    """Ingest a single file: extract → chunk → embed → store."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}")

    source_type = SUPPORTED_EXTENSIONS[ext]
    title = file_path.stem

    if progress_callback:
        await progress_callback(f"Extracting text from {file_path.name}...")

    text, page_breaks = await extract_text(file_path)
    if not text.strip():
        return {"status": "skipped", "reason": "Empty content", "file": str(file_path)}

    content_hash = compute_hash(text)
    if db.document_exists(library_id, content_hash):
        return {"status": "skipped", "reason": "Duplicate", "file": str(file_path)}

    if progress_callback:
        await progress_callback(f"Chunking {title}...")

    chunks = chunk_text(text, page_breaks=page_breaks)

    if progress_callback:
        await progress_callback(f"Embedding {len(chunks)} chunks...")

    # Embed in batches
    chunk_texts = [c["text"] for c in chunks]
    embeddings = await llm.embed(chunk_texts)

    # Store in SQLite
    doc_id = db.add_document(
        library_id=library_id, title=title, source_type=source_type,
        content_hash=content_hash, source_path=str(file_path),
        metadata={"pages": len(page_breaks) if page_breaks else None},
    )

    # Store in ChromaDB
    chunk_ids = vector_store.add_chunks(
        library_id=library_id, chunks=chunks, embeddings=embeddings,
        document_id=doc_id, document_title=title, source_type=source_type,
    )

    for i, chunk in enumerate(chunks):
        chunk["embedding_id"] = chunk_ids[i] if i < len(chunk_ids) else None

    db.add_chunks(doc_id, library_id, chunks)

    # Update library stats
    stats = db.get_library_stats(library_id)
    db.update_library(library_id, doc_count=stats["documents"], chunk_count=stats["chunks"])

    return {
        "status": "success", "file": str(file_path), "doc_id": doc_id,
        "title": title, "chunks": len(chunks), "source_type": source_type,
    }


async def ingest_folder(
    folder_path: Path,
    library_id: str,
    db: MetadataDB,
    vector_store: VectorStore,
    llm: LLMProvider,
    progress_callback: Callable | None = None,
) -> AsyncIterator[dict]:
    """Ingest all supported files from a folder."""
    folder_path = Path(folder_path)
    if not folder_path.exists() or not folder_path.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(folder_path.rglob(f"*{ext}"))
    files = sorted(set(files))

    if not files:
        yield {"status": "empty", "message": "No supported files found"}
        return

    yield {"status": "start", "total": len(files)}

    success, skipped, errors = 0, 0, 0
    for i, fp in enumerate(files):
        try:
            result = await ingest_file(fp, library_id, db, vector_store, llm, progress_callback)
            result["progress"] = f"{i + 1}/{len(files)}"
            if result["status"] == "success":
                success += 1
            else:
                skipped += 1
            yield result
        except Exception as e:
            errors += 1
            yield {"status": "error", "file": str(fp), "error": str(e), "progress": f"{i + 1}/{len(files)}"}

    yield {"status": "complete", "total": len(files), "success": success, "skipped": skipped, "errors": errors}


async def ingest_upload(
    file_content: bytes,
    filename: str,
    library_id: str,
    db: MetadataDB,
    vector_store: VectorStore,
    llm: LLMProvider,
    upload_dir: Path | None = None,
) -> dict:
    """Ingest an uploaded file."""
    from backend.config import settings
    upload_dir = upload_dir or Path(settings.DATA_DIR) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Browsers may send relative paths for folder uploads. Preserve structure
    # but prevent escaping the upload root.
    parts = [p for p in Path(filename).parts if p not in ("", ".", "..", "/", "\\")]
    safe_relative = Path(*parts) if parts else Path("upload.bin")
    file_path = (upload_dir / safe_relative).resolve()
    upload_root = upload_dir.resolve()
    if file_path != upload_root and upload_root not in file_path.parents:
        raise ValueError("Invalid upload path")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(file_content)

    try:
        return await ingest_file(file_path, library_id, db, vector_store, llm)
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise
