"""Source management routes."""

import os
from datetime import datetime
from pathlib import Path as FilePath

from fastapi import APIRouter, HTTPException, UploadFile, File, BackgroundTasks
from backend.api.schemas import SourceCreate, SourceResponse
from backend.main import get_db, get_vector_store, get_llm

router = APIRouter(tags=["sources"])
SUPPORTED_SOURCE_TYPES = {"local_folder", "chromadb"}


@router.get("/api/browse")
async def browse_filesystem(path: str = "~"):
    """Browse local filesystem directories for folder selection."""
    target = FilePath(os.path.expanduser(path)).resolve()

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {target}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    entries = []
    try:
        for entry in sorted(target.iterdir()):
            # Skip hidden files and known irrelevant dirs
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                # Count supported files inside (non-recursive, fast check)
                file_count = 0
                try:
                    for f in entry.iterdir():
                        if f.suffix.lower() in {".pdf", ".epub", ".docx", ".doc", ".txt", ".md"}:
                            file_count += 1
                except PermissionError:
                    pass
                entries.append({
                    "name": entry.name,
                    "path": str(entry),
                    "type": "directory",
                    "file_count": file_count,
                })
            else:
                if entry.suffix.lower() in {".pdf", ".epub", ".docx", ".doc", ".txt", ".md"}:
                    entries.append({
                        "name": entry.name,
                        "path": str(entry),
                        "type": "file",
                        "size": entry.stat().st_size,
                    })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Count total supported files in this directory (non-recursive)
    supported_here = sum(1 for e in entries if e["type"] == "file")

    return {
        "current_path": str(target),
        "parent_path": str(target.parent) if target != target.parent else None,
        "entries": entries,
        "supported_files": supported_here,
    }


@router.get("/api/libraries/{lib_id}/sources", response_model=list[SourceResponse])
async def list_sources(lib_id: str):
    db = get_db()
    if not db.get_library(lib_id):
        raise HTTPException(status_code=404, detail="Library not found")
    sources = db.get_sources(lib_id)
    return [_source_response(s) for s in sources]


@router.post("/api/libraries/{lib_id}/sources", response_model=SourceResponse)
async def add_source(lib_id: str, body: SourceCreate, background_tasks: BackgroundTasks):
    db = get_db()
    if not db.get_library(lib_id):
        raise HTTPException(status_code=404, detail="Library not found")

    if body.source_type not in SUPPORTED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source_type '{body.source_type}'. Supported: local_folder, chromadb",
        )

    if body.source_type == "chromadb":
        raise HTTPException(
            status_code=400,
            detail="Use /api/libraries/{lib_id}/connect-chromadb for chromadb sources.",
        )

    source = db.add_source(lib_id, body.source_type, body.config)

    # Start ingestion in background if it's a folder source
    if body.source_type == "local_folder" and body.config.get("path"):
        background_tasks.add_task(_ingest_folder_source, source.id, lib_id, body.config["path"])

    return _source_response(source)


@router.post("/api/libraries/{lib_id}/upload")
async def upload_files(
    lib_id: str,
    files: list[UploadFile] = File(...),
):
    """Upload files directly to a library."""
    from backend.ingestion.ingest import ingest_upload

    db = get_db()
    vs = get_vector_store()
    llm = get_llm()

    if not db.get_library(lib_id):
        raise HTTPException(status_code=404, detail="Library not found")

    upload_source = next((s for s in db.get_sources(lib_id) if s.source_type == "upload"), None)
    if upload_source is None:
        upload_source = db.add_source(lib_id, "upload", {"label": "Uploaded files"})

    results = []
    success_count = 0
    for file in files:
        try:
            content = await file.read()
            result = await ingest_upload(
                file_content=content, filename=file.filename,
                library_id=lib_id, db=db, vector_store=vs, llm=llm,
            )
            results.append(result)
            if result.get("status") == "success":
                success_count += 1
        except Exception as e:
            results.append({"status": "error", "file": file.filename, "error": str(e)})

    # Update library stats
    stats = db.get_library_stats(lib_id)
    db.update_library(lib_id, doc_count=stats["documents"], chunk_count=stats["chunks"])
    db.update_source(
        upload_source.id,
        doc_count=upload_source.doc_count + success_count,
        last_synced=datetime.now(),
    )

    return {
        "results": results,
        "summary": {
            "total": len(results),
            "success": success_count,
            "errors": len([r for r in results if r.get("status") == "error"]),
            "skipped": len([r for r in results if r.get("status") == "skipped"]),
        },
    }


@router.post("/api/libraries/{lib_id}/connect-chromadb")
async def connect_chromadb(lib_id: str, body: SourceCreate):
    """Connect an existing ChromaDB directory as a source."""
    import chromadb

    db = get_db()
    if not db.get_library(lib_id):
        raise HTTPException(status_code=404, detail="Library not found")

    chroma_path = body.config.get("path", "")
    if not chroma_path:
        raise HTTPException(status_code=400, detail="Path is required")

    target = FilePath(os.path.expanduser(chroma_path)).resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {target}")

    # Try to connect and list collections
    try:
        client = chromadb.PersistentClient(path=str(target))
        collections = client.list_collections()
        collection_info = []
        total_chunks = 0
        for col in collections:
            count = col.count()
            total_chunks += count
            collection_info.append({"name": col.name, "count": count})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Not a valid ChromaDB directory: {e}")

    # Save as a source
    source = db.add_source(lib_id, "chromadb", {
        "path": str(target),
        "collections": [c["name"] for c in collection_info],
    })
    db.update_source(source.id, doc_count=len(collection_info))

    # Update library chunk count from the external ChromaDB
    db.update_library(lib_id, chunk_count=total_chunks, status="ready")

    return {
        **_source_response(source),
        "collections": collection_info,
        "total_chunks": total_chunks,
    }


@router.post("/api/probe-chromadb")
async def probe_chromadb(body: dict):
    """Probe a ChromaDB directory to see what's inside."""
    import chromadb

    chroma_path = body.get("path", "")
    if not chroma_path:
        raise HTTPException(status_code=400, detail="Path is required")

    target = FilePath(os.path.expanduser(chroma_path)).resolve()
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {target}")

    try:
        client = chromadb.PersistentClient(path=str(target))
        collections = client.list_collections()
        info = []
        total = 0
        for col in collections:
            count = col.count()
            total += count
            info.append({"name": col.name, "count": count})
        return {"valid": True, "collections": info, "total_chunks": total, "path": str(target)}
    except Exception as e:
        return {"valid": False, "error": str(e), "path": str(target)}


@router.delete("/api/sources/{src_id}")
async def delete_source(src_id: str):
    db = get_db()
    source = db.get_source(src_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    db.delete_source(src_id)
    return {"status": "deleted"}


@router.post("/api/sources/{src_id}/sync")
async def sync_source(src_id: str, background_tasks: BackgroundTasks):
    db = get_db()
    source = db.get_source(src_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if source.source_type == "local_folder":
        path = source.config.get("path")
        if path:
            background_tasks.add_task(_ingest_folder_source, src_id, source.library_id, path)
            return {"status": "syncing"}

    return {"status": "noop", "message": f"Source type '{source.source_type}' has no sync operation."}


async def _ingest_folder_source(source_id: str, library_id: str, folder_path: str):
    """Background task to ingest a folder source."""
    from backend.ingestion.ingest import ingest_folder
    from pathlib import Path

    db = get_db()
    vs = get_vector_store()
    llm = get_llm()

    try:
        doc_count = 0
        async for result in ingest_folder(Path(folder_path), library_id, db, vs, llm):
            if result.get("status") == "success":
                doc_count += 1

        db.update_source(source_id, doc_count=doc_count)
        stats = db.get_library_stats(library_id)
        db.update_library(library_id, doc_count=stats["documents"], chunk_count=stats["chunks"])

    except Exception as e:
        import logging
        logging.error(f"Folder ingestion failed: {e}")


def _source_response(s) -> dict:
    return {
        "id": s.id, "library_id": s.library_id, "source_type": s.source_type,
        "config": s.config, "doc_count": s.doc_count,
        "last_synced": s.last_synced.isoformat() if s.last_synced else None,
        "created_at": s.created_at.isoformat(),
    }
