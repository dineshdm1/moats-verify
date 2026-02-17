"""SQLite storage for document metadata and library state."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator
import json

from moats_library.config import get_settings


@dataclass
class Document:
    """Document metadata."""

    id: int | None
    title: str
    source_type: str  # 'pdf', 'epub', 'docx', 'txt', 'md', 'link', 'note'
    source_path: str | None
    source_url: str | None
    content_hash: str
    chunk_count: int
    created_at: datetime
    metadata: dict


@dataclass
class IngestionJob:
    """Ingestion job for tracking folder ingestion."""

    id: int | None
    folder_path: str
    status: str  # 'pending', 'running', 'completed', 'failed', 'cancelled'
    total: int
    processed: int
    success: int
    skipped: int
    errors: int
    current_file: str
    last_error: str | None
    retry_count: int
    max_retries: int
    created_at: datetime
    updated_at: datetime


class LibraryDB:
    """SQLite database for document metadata."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_settings().sqlite_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_path TEXT,
                    source_url TEXT,
                    content_hash TEXT UNIQUE NOT NULL,
                    chunk_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    start_page INTEGER,
                    end_page INTEGER,
                    embedding_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    total INTEGER DEFAULT 0,
                    processed INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 0,
                    skipped INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    current_file TEXT DEFAULT '',
                    last_error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs(status);
            """)
            conn.commit()

    def add_document(
        self,
        title: str,
        source_type: str,
        content_hash: str,
        source_path: str | None = None,
        source_url: str | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Add a document and return its ID."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO documents (title, source_type, source_path, source_url, content_hash, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, source_type, source_path, source_url, content_hash, json.dumps(metadata or {})),
            )
            conn.commit()
            return cursor.lastrowid

    def document_exists(self, content_hash: str) -> bool:
        """Check if a document with this hash already exists."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM documents WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            return row is not None

    def get_document(self, doc_id: int) -> Document | None:
        """Get document by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if not row:
                return None
            return Document(
                id=row["id"],
                title=row["title"],
                source_type=row["source_type"],
                source_path=row["source_path"],
                source_url=row["source_url"],
                content_hash=row["content_hash"],
                chunk_count=row["chunk_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
                metadata=json.loads(row["metadata"]),
            )

    def get_all_documents(self) -> list[Document]:
        """Get all documents."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC"
            ).fetchall()
            return [
                Document(
                    id=row["id"],
                    title=row["title"],
                    source_type=row["source_type"],
                    source_path=row["source_path"],
                    source_url=row["source_url"],
                    content_hash=row["content_hash"],
                    chunk_count=row["chunk_count"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    metadata=json.loads(row["metadata"]),
                )
                for row in rows
            ]

    def add_chunks(self, document_id: int, chunks: list[dict]) -> None:
        """Add chunks for a document."""
        with self._get_conn() as conn:
            for i, chunk in enumerate(chunks):
                conn.execute(
                    """
                    INSERT INTO chunks (document_id, chunk_index, text, start_page, end_page, embedding_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        i,
                        chunk["text"],
                        chunk.get("start_page"),
                        chunk.get("end_page"),
                        chunk.get("embedding_id"),
                    ),
                )
            conn.execute(
                "UPDATE documents SET chunk_count = ? WHERE id = ?",
                (len(chunks), document_id),
            )
            conn.commit()

    def get_chunks(self, document_id: int) -> list[dict]:
        """Get all chunks for a document."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index",
                (document_id,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "start_page": row["start_page"],
                    "end_page": row["end_page"],
                    "embedding_id": row["embedding_id"],
                }
                for row in rows
            ]

    def add_note(self, title: str, content: str, tags: list[str] | None = None) -> int:
        """Add a note."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO notes (title, content, tags) VALUES (?, ?, ?)",
                (title, content, json.dumps(tags or [])),
            )
            conn.commit()
            return cursor.lastrowid

    def get_stats(self) -> dict:
        """Get library statistics."""
        with self._get_conn() as conn:
            doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]

            by_type = {}
            for row in conn.execute(
                "SELECT source_type, COUNT(*) as cnt FROM documents GROUP BY source_type"
            ).fetchall():
                by_type[row["source_type"]] = row["cnt"]

            return {
                "documents": doc_count,
                "chunks": chunk_count,
                "notes": note_count,
                "conversations": conv_count,
                "by_type": by_type,
            }

    # ============ Ingestion Job Management ============

    def create_ingestion_job(self, folder_path: str) -> int:
        """Create a new ingestion job and return its ID."""
        with self._get_conn() as conn:
            # Cancel any existing pending/running jobs for same folder
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                WHERE folder_path = ? AND status IN ('pending', 'running')
                """,
                (folder_path,),
            )
            # Create new job
            cursor = conn.execute(
                """
                INSERT INTO ingestion_jobs (folder_path, status)
                VALUES (?, 'pending')
                """,
                (folder_path,),
            )
            conn.commit()
            return cursor.lastrowid

    def get_job(self, job_id: int) -> IngestionJob | None:
        """Get job by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def get_active_job(self) -> IngestionJob | None:
        """Get currently running job, if any."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_jobs WHERE status = 'running' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return self._row_to_job(row)

    def get_resumable_jobs(self) -> list[IngestionJob]:
        """Get jobs that can be resumed (failed/interrupted with retries remaining)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ingestion_jobs
                WHERE status IN ('failed', 'running')
                AND retry_count < max_retries
                ORDER BY updated_at DESC
                """
            ).fetchall()
            return [self._row_to_job(row) for row in rows]

    def start_job(self, job_id: int, total: int) -> None:
        """Mark job as running with total count."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'running', total = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (total, job_id),
            )
            conn.commit()

    def update_job_progress(
        self,
        job_id: int,
        processed: int,
        success: int,
        skipped: int,
        errors: int,
        current_file: str,
    ) -> None:
        """Update job progress."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET processed = ?, success = ?, skipped = ?, errors = ?,
                    current_file = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (processed, success, skipped, errors, current_file, job_id),
            )
            conn.commit()

    def complete_job(self, job_id: int) -> None:
        """Mark job as completed."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'completed', current_file = '', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (job_id,),
            )
            conn.commit()

    def fail_job(self, job_id: int, error: str) -> None:
        """Mark job as failed with error message."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'failed', last_error = ?, retry_count = retry_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error[:500], job_id),
            )
            conn.commit()

    def cancel_job(self, job_id: int) -> None:
        """Mark job as cancelled."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (job_id,),
            )
            conn.commit()

    def _row_to_job(self, row) -> IngestionJob:
        """Convert a database row to IngestionJob."""
        return IngestionJob(
            id=row["id"],
            folder_path=row["folder_path"],
            status=row["status"],
            total=row["total"],
            processed=row["processed"],
            success=row["success"],
            skipped=row["skipped"],
            errors=row["errors"],
            current_file=row["current_file"] or "",
            last_error=row["last_error"],
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
