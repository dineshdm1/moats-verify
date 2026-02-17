"""Library CRUD routes."""

import threading
from fastapi import APIRouter, HTTPException, BackgroundTasks
from backend.api.schemas import LibraryCreate, LibraryUpdate, LibraryResponse, BuildStatusResponse
from backend.main import get_db, get_vector_store

router = APIRouter(prefix="/api/libraries", tags=["libraries"])

# Track cancellation flags per job_id
_cancel_flags: dict[str, threading.Event] = {}


@router.get("", response_model=list[LibraryResponse])
async def list_libraries():
    db = get_db()
    libraries = db.get_all_libraries()
    return [_lib_response(lib) for lib in libraries]


@router.post("", response_model=LibraryResponse)
async def create_library(body: LibraryCreate):
    db = get_db()
    lib = db.create_library(name=body.name, description=body.description)
    # If this is the first library, activate it
    all_libs = db.get_all_libraries()
    if len(all_libs) == 1:
        db.activate_library(lib.id)
        lib = db.get_library(lib.id)
    return _lib_response(lib)


@router.get("/{lib_id}", response_model=LibraryResponse)
async def get_library(lib_id: str):
    db = get_db()
    lib = db.get_library(lib_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Library not found")
    return _lib_response(lib)


@router.put("/{lib_id}", response_model=LibraryResponse)
async def update_library(lib_id: str, body: LibraryUpdate):
    db = get_db()
    if not db.get_library(lib_id):
        raise HTTPException(status_code=404, detail="Library not found")
    updates = body.model_dump(exclude_none=True)
    lib = db.update_library(lib_id, **updates)
    return _lib_response(lib)


@router.delete("/{lib_id}")
async def delete_library(lib_id: str):
    db = get_db()
    vs = get_vector_store()
    if not db.get_library(lib_id):
        raise HTTPException(status_code=404, detail="Library not found")
    vs.delete_collection(lib_id)
    db.delete_library(lib_id)
    return {"status": "deleted"}


@router.post("/{lib_id}/activate")
async def activate_library(lib_id: str):
    db = get_db()
    if not db.get_library(lib_id):
        raise HTTPException(status_code=404, detail="Library not found")
    db.activate_library(lib_id)
    return {"status": "activated"}


@router.post("/{lib_id}/build")
async def start_build(lib_id: str, background_tasks: BackgroundTasks):
    db = get_db()
    lib = db.get_library(lib_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Library not found")

    job_id = db.create_build_job(lib_id)
    cancel_event = threading.Event()
    _cancel_flags[job_id] = cancel_event
    background_tasks.add_task(_run_build, job_id, lib_id, cancel_event)
    return {"job_id": job_id, "status": "started"}


@router.post("/{lib_id}/build/cancel")
async def cancel_build(lib_id: str):
    db = get_db()
    # Find the latest running build job
    with db._conn() as conn:
        row = conn.execute(
            "SELECT id FROM build_jobs WHERE library_id = ? AND status IN ('pending', 'running') ORDER BY created_at DESC LIMIT 1",
            (lib_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active build to cancel")

    job_id = row["id"]
    cancel_event = _cancel_flags.get(job_id)
    if cancel_event:
        cancel_event.set()
    db.update_build_job(job_id, status="cancelled", current_step="cancelled")
    _cancel_flags.pop(job_id, None)
    return {"status": "cancelled"}


@router.get("/{lib_id}/build/status", response_model=BuildStatusResponse)
async def get_build_status(lib_id: str):
    db = get_db()
    with db._conn() as conn:
        row = conn.execute(
            "SELECT id FROM build_jobs WHERE library_id = ? ORDER BY created_at DESC LIMIT 1",
            (lib_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No build jobs found")
    job = db.get_build_job(row["id"])
    job["job_id"] = job.pop("id")
    return job


async def _run_build(job_id: str, library_id: str, cancel_event: threading.Event):
    """Background task to refresh local library stats."""

    db = get_db()

    try:
        if cancel_event.is_set():
            return

        db.update_build_job(job_id, status="running", current_step="ingestion", progress=0.1)

        if cancel_event.is_set():
            db.update_build_job(job_id, status="cancelled", current_step="cancelled")
            return

        db.update_build_job(
            job_id,
            current_step="chunking",
            progress=0.4,
            steps_completed=["ingestion"],
        )

        if cancel_event.is_set():
            db.update_build_job(job_id, status="cancelled", current_step="cancelled")
            return

        db.update_build_job(
            job_id,
            current_step="embedding",
            progress=0.7,
            steps_completed=["ingestion", "chunking"],
        )

        if cancel_event.is_set():
            db.update_build_job(job_id, status="cancelled", current_step="cancelled")
            return

        # Update library stats
        stats = db.get_library_stats(library_id)
        db.update_library(library_id, doc_count=stats["documents"], chunk_count=stats["chunks"])

        db.update_build_job(
            job_id, status="completed", progress=1.0,
            current_step="done",
            steps_completed=["ingestion", "chunking", "embedding"],
        )

    except InterruptedError:
        db.update_build_job(job_id, status="cancelled", current_step="cancelled")
    except Exception as e:
        db.update_build_job(job_id, status="failed", error=str(e))
    finally:
        _cancel_flags.pop(job_id, None)


def _lib_response(lib) -> dict:
    return {
        "id": lib.id, "name": lib.name, "description": lib.description,
        "is_active": lib.is_active, "doc_count": lib.doc_count,
        "chunk_count": lib.chunk_count, "status": lib.status,
        "build_progress": lib.build_progress,
        "created_at": lib.created_at.isoformat(),
        "updated_at": lib.updated_at.isoformat(),
    }
