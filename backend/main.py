"""FastAPI application — Moats Verify backend."""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.storage.sqlite import MetadataDB
from backend.storage.chromadb import VectorStore
from backend.llm.provider import LLMProvider, LLMConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Singleton instances ──

_db: MetadataDB | None = None
_vector_store: VectorStore | None = None
_llm: LLMProvider | None = None


def get_db() -> MetadataDB:
    global _db
    if _db is None:
        _db = MetadataDB()
    return _db


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store


def get_llm() -> LLMProvider:
    global _llm
    if _llm is None:
        # Try to load saved config from DB
        db = get_db()
        saved = db.get_setting("llm_config")
        if saved:
            try:
                config = LLMConfig.from_dict(json.loads(saved))
                _llm = LLMProvider(config)
            except Exception:
                _llm = LLMProvider()
        else:
            _llm = LLMProvider()
    return _llm


def reload_llm(config_dict: dict):
    global _llm
    config = LLMConfig.from_dict(config_dict)
    _llm = LLMProvider(config)


# ── App lifecycle ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Moats Verify starting up...")
    get_db()
    get_vector_store()
    yield
    logger.info("Moats Verify shut down")


# ── Create app ──

app = FastAPI(
    title="Moats Verify",
    description="Verification engine — Is this claim supported by your documents?",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check ──

@app.get("/api/health")
async def health():
    db = get_db()
    get_vector_store()
    active_lib = db.get_active_library()
    return {
        "status": "ok",
        "active_library": {
            "id": active_lib.id,
            "name": active_lib.name,
            "doc_count": active_lib.doc_count,
            "chunk_count": active_lib.chunk_count,
            "status": active_lib.status,
        } if active_lib else None,
    }


@app.head("/api/health")
async def health_head():
    return Response(status_code=200)


# ── Register routes ──

from backend.api.routes.libraries import router as libraries_router
from backend.api.routes.sources import router as sources_router
from backend.api.routes.verify import router as verify_router
from backend.api.routes.settings import router as settings_router

app.include_router(libraries_router)
app.include_router(sources_router)
app.include_router(verify_router)
app.include_router(settings_router)
