"""Pydantic models for API request/response schemas."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ── Libraries ──

class LibraryCreate(BaseModel):
    name: str
    description: str = ""

class LibraryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class LibraryResponse(BaseModel):
    id: str
    name: str
    description: str
    is_active: bool
    doc_count: int
    chunk_count: int
    status: str
    build_progress: float
    created_at: str
    updated_at: str

# ── Sources ──

class SourceCreate(BaseModel):
    source_type: str  # local_folder, chromadb
    config: dict = {}

class SourceResponse(BaseModel):
    id: str
    library_id: str
    source_type: str
    config: dict
    doc_count: int
    last_synced: Optional[str] = None
    created_at: str

# ── Verify ──

class VerifyRequest(BaseModel):
    text: str
    library_id: Optional[str] = None

class VerdictResponse(BaseModel):
    claim: str
    claim_type: str
    verdict: str
    confidence: float
    reasoning: str
    evidence_used: str
    contradiction_type: Optional[str] = None
    contradiction_explanation: Optional[str] = None
    sources: list[dict] = []
    temporal_context: Optional[dict] = None

class VerifyResponse(BaseModel):
    verification_id: str
    trust_score: float
    total_claims: int
    supported: int
    partially_supported: int
    contradicted: int
    conflicting: int
    no_evidence: int
    verdicts: list[dict]

class VerificationHistoryItem(BaseModel):
    id: str
    library_id: str
    input_text: str
    trust_score: float
    claim_count: int
    created_at: str

# ── Settings ──

class LLMSettingsUpdate(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    chat_model: Optional[str] = None
    embedding_model: Optional[str] = None

class ConnectionConfig(BaseModel):
    provider: str
    config: dict

class TestResult(BaseModel):
    status: str
    message: Optional[str] = None
    error: Optional[str] = None

# ── Build ──

class BuildStatusResponse(BaseModel):
    job_id: str
    status: str
    current_step: str
    progress: float
    steps_completed: list[str]
    error: Optional[str] = None
