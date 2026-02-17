"""SQLite storage for document metadata, libraries, and verification history."""

import sqlite3
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Generator

from backend.config import settings


@dataclass
class Library:
    id: str
    name: str
    description: str
    is_active: bool
    doc_count: int
    chunk_count: int
    status: str  # ready, building, error
    build_progress: float
    created_at: datetime
    updated_at: datetime


@dataclass
class Source:
    id: str
    library_id: str
    source_type: str  # local_folder, upload, s3, gcs, azure_blob, vector_store
    config: dict
    doc_count: int
    last_synced: datetime | None
    created_at: datetime


@dataclass
class Document:
    id: int | None
    library_id: str
    title: str
    source_type: str
    source_path: str | None
    content_hash: str
    chunk_count: int
    created_at: datetime
    metadata: dict


@dataclass
class VerificationResult:
    id: str
    library_id: str
    input_text: str
    trust_score: float
    claims: list[dict]
    created_at: datetime


class MetadataDB:
    """SQLite database for all metadata."""

    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path or settings.SQLITE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS libraries (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    is_active INTEGER DEFAULT 0,
                    doc_count INTEGER DEFAULT 0,
                    chunk_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'empty',
                    build_progress REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    config TEXT DEFAULT '{}',
                    doc_count INTEGER DEFAULT 0,
                    last_synced TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_path TEXT,
                    content_hash TEXT NOT NULL,
                    chunk_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT DEFAULT '{}',
                    FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    library_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    start_page INTEGER,
                    end_page INTEGER,
                    paragraph INTEGER,
                    embedding_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS verifications (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    trust_score REAL,
                    claims TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS build_jobs (
                    id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    current_step TEXT DEFAULT '',
                    steps_completed TEXT DEFAULT '[]',
                    total_steps INTEGER DEFAULT 6,
                    progress REAL DEFAULT 0.0,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (library_id) REFERENCES libraries(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_documents_library ON documents(library_id);
                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_library ON chunks(library_id);
                CREATE INDEX IF NOT EXISTS idx_sources_library ON sources(library_id);
                CREATE INDEX IF NOT EXISTS idx_verifications_library ON verifications(library_id);
                CREATE INDEX IF NOT EXISTS idx_verifications_created ON verifications(created_at DESC);
            """)
            conn.commit()

    # ── Libraries ──

    def create_library(self, name: str, description: str = "") -> Library:
        lib_id = str(uuid.uuid4())[:8]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO libraries (id, name, description) VALUES (?, ?, ?)",
                (lib_id, name, description),
            )
            conn.commit()
        return self.get_library(lib_id)

    def get_library(self, lib_id: str) -> Library | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM libraries WHERE id = ?", (lib_id,)).fetchone()
            return self._row_to_library(row) if row else None

    def get_all_libraries(self) -> list[Library]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM libraries ORDER BY created_at DESC").fetchall()
            return [self._row_to_library(r) for r in rows]

    def get_active_library(self) -> Library | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM libraries WHERE is_active = 1 LIMIT 1").fetchone()
            return self._row_to_library(row) if row else None

    def activate_library(self, lib_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE libraries SET is_active = 0")
            conn.execute("UPDATE libraries SET is_active = 1 WHERE id = ?", (lib_id,))
            conn.commit()

    def update_library(self, lib_id: str, **kwargs) -> Library:
        allowed = {"name", "description", "status", "build_progress", "doc_count", "chunk_count"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return self.get_library(lib_id)
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [lib_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE libraries SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", vals)
            conn.commit()
        return self.get_library(lib_id)

    def delete_library(self, lib_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM libraries WHERE id = ?", (lib_id,))
            conn.commit()

    # ── Sources ──

    def add_source(self, library_id: str, source_type: str, config: dict) -> Source:
        src_id = str(uuid.uuid4())[:8]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sources (id, library_id, source_type, config) VALUES (?, ?, ?, ?)",
                (src_id, library_id, source_type, json.dumps(config)),
            )
            conn.commit()
        return self.get_source(src_id)

    def get_source(self, src_id: str) -> Source | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (src_id,)).fetchone()
            return self._row_to_source(row) if row else None

    def get_sources(self, library_id: str) -> list[Source]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sources WHERE library_id = ? ORDER BY created_at", (library_id,)
            ).fetchall()
            return [self._row_to_source(r) for r in rows]

    def update_source(self, src_id: str, **kwargs) -> Source:
        allowed = {"config", "doc_count", "last_synced"}
        fields = {}
        for k, v in kwargs.items():
            if k in allowed:
                fields[k] = json.dumps(v) if k == "config" else v
        if not fields:
            return self.get_source(src_id)
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [src_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE sources SET {sets} WHERE id = ?", vals)
            conn.commit()
        return self.get_source(src_id)

    def delete_source(self, src_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sources WHERE id = ?", (src_id,))
            conn.commit()

    # ── Documents ──

    def add_document(self, library_id: str, title: str, source_type: str,
                     content_hash: str, source_path: str | None = None,
                     metadata: dict | None = None) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """INSERT INTO documents (library_id, title, source_type, source_path, content_hash, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (library_id, title, source_type, source_path, content_hash, json.dumps(metadata or {})),
            )
            conn.commit()
            return cursor.lastrowid

    def document_exists(self, library_id: str, content_hash: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM documents WHERE library_id = ? AND content_hash = ?",
                (library_id, content_hash),
            ).fetchone()
            return row is not None

    def get_documents(self, library_id: str) -> list[Document]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE library_id = ? ORDER BY created_at DESC", (library_id,)
            ).fetchall()
            return [self._row_to_document(r) for r in rows]

    def update_document_chunks(self, doc_id: int, chunk_count: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE documents SET chunk_count = ? WHERE id = ?", (chunk_count, doc_id))
            conn.commit()

    # ── Chunks ──

    def add_chunks(self, document_id: int, library_id: str, chunks: list[dict]) -> None:
        with self._conn() as conn:
            for i, chunk in enumerate(chunks):
                conn.execute(
                    """INSERT INTO chunks (document_id, library_id, chunk_index, text,
                       start_page, end_page, paragraph, embedding_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (document_id, library_id, i, chunk["text"],
                     chunk.get("start_page"), chunk.get("end_page"),
                     chunk.get("paragraph"), chunk.get("embedding_id")),
                )
            conn.execute("UPDATE documents SET chunk_count = ? WHERE id = ?", (len(chunks), document_id))
            conn.commit()

    def get_library_stats(self, library_id: str) -> dict:
        with self._conn() as conn:
            doc_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE library_id = ?", (library_id,)
            ).fetchone()[0]
            chunk_count = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE library_id = ?", (library_id,)
            ).fetchone()[0]
            return {"documents": doc_count, "chunks": chunk_count}

    # ── Verifications ──

    def save_verification(self, library_id: str, input_text: str,
                          trust_score: float, claims: list[dict]) -> str:
        ver_id = str(uuid.uuid4())[:8]
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO verifications (id, library_id, input_text, trust_score, claims)
                   VALUES (?, ?, ?, ?, ?)""",
                (ver_id, library_id, input_text, trust_score, json.dumps(claims)),
            )
            conn.commit()
        return ver_id

    def get_verification(self, ver_id: str) -> VerificationResult | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM verifications WHERE id = ?", (ver_id,)).fetchone()
            return self._row_to_verification(row) if row else None

    def get_verification_history(self, library_id: str | None = None,
                                  limit: int = 50) -> list[VerificationResult]:
        with self._conn() as conn:
            if library_id:
                rows = conn.execute(
                    "SELECT * FROM verifications WHERE library_id = ? ORDER BY created_at DESC LIMIT ?",
                    (library_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM verifications ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._row_to_verification(r) for r in rows]

    def delete_verification(self, ver_id: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM verifications WHERE id = ?", (ver_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ── Build Jobs ──

    def create_build_job(self, library_id: str) -> str:
        job_id = str(uuid.uuid4())[:8]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO build_jobs (id, library_id, status) VALUES (?, ?, 'pending')",
                (job_id, library_id),
            )
            conn.execute(
                "UPDATE libraries SET status = 'building', build_progress = 0 WHERE id = ?",
                (library_id,),
            )
            conn.commit()
        return job_id

    def update_build_job(self, job_id: str, **kwargs) -> None:
        allowed = {"status", "current_step", "steps_completed", "progress", "error"}
        fields = {}
        for k, v in kwargs.items():
            if k in allowed:
                fields[k] = json.dumps(v) if k == "steps_completed" else v
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [job_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE build_jobs SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", vals)
            if "progress" in fields:
                row = conn.execute("SELECT library_id FROM build_jobs WHERE id = ?", (job_id,)).fetchone()
                if row:
                    conn.execute(
                        "UPDATE libraries SET build_progress = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (fields["progress"], row["library_id"]),
                    )
            if kwargs.get("status") == "completed":
                row = conn.execute("SELECT library_id FROM build_jobs WHERE id = ?", (job_id,)).fetchone()
                if row:
                    conn.execute(
                        "UPDATE libraries SET status = 'ready', build_progress = 1.0 WHERE id = ?",
                        (row["library_id"],),
                    )
            elif kwargs.get("status") == "failed":
                row = conn.execute("SELECT library_id FROM build_jobs WHERE id = ?", (job_id,)).fetchone()
                if row:
                    conn.execute("UPDATE libraries SET status = 'error' WHERE id = ?", (row["library_id"],))
            conn.commit()

    def get_build_job(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM build_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "library_id": row["library_id"],
                "status": row["status"],
                "current_step": row["current_step"],
                "steps_completed": json.loads(row["steps_completed"]),
                "total_steps": row["total_steps"],
                "progress": row["progress"],
                "error": row["error"],
            }

    # ── Settings ──

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (key, value),
            )
            conn.commit()

    def get_all_settings(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

    # ── Row converters ──

    def _row_to_library(self, row) -> Library:
        return Library(
            id=row["id"], name=row["name"], description=row["description"],
            is_active=bool(row["is_active"]), doc_count=row["doc_count"],
            chunk_count=row["chunk_count"], status=row["status"],
            build_progress=row["build_progress"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _row_to_source(self, row) -> Source:
        return Source(
            id=row["id"], library_id=row["library_id"], source_type=row["source_type"],
            config=json.loads(row["config"]), doc_count=row["doc_count"],
            last_synced=datetime.fromisoformat(row["last_synced"]) if row["last_synced"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_document(self, row) -> Document:
        return Document(
            id=row["id"], library_id=row["library_id"], title=row["title"],
            source_type=row["source_type"], source_path=row["source_path"],
            content_hash=row["content_hash"], chunk_count=row["chunk_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata"]),
        )

    def _row_to_verification(self, row) -> VerificationResult:
        return VerificationResult(
            id=row["id"], library_id=row["library_id"], input_text=row["input_text"],
            trust_score=row["trust_score"], claims=json.loads(row["claims"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
