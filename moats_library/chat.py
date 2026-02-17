"""Chainlit chat interface for Moats Library - Powered by Emma."""

import asyncio
import logging
import os
import signal
import shutil
import sys
import uuid
from pathlib import Path
from typing import Optional

import chainlit as cl
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    sig_name = signal.Signals(signum).name
    logger.warning(f"Received signal {sig_name} ({signum}). Shutting down gracefully...")
    # Don't exit here - let the process handle it naturally
    # This just logs the signal for debugging


# Register signal handlers
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

logger.info("Emma chat module loaded - signal handlers registered")


# Health check endpoints for Docker/Kubernetes
# These are registered directly on Chainlit's FastAPI app at module load time
def _register_health_endpoints():
    """Register health check endpoints on Chainlit's FastAPI app."""
    try:
        from chainlit.server import app

        @app.get("/api/health")
        async def health_check():
            """Health check endpoint for container orchestration."""
            try:
                db_instance, vector_store_instance, _ = get_stores()
                stats = db_instance.get_stats()
                active_job = db_instance.get_active_job()

                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "healthy",
                        "documents": stats.get("documents", 0),
                        "chunks": stats.get("chunks", 0),
                        "ingestion_active": active_job is not None,
                        "ingestion_job_id": active_job.id if active_job else None,
                    }
                )
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                return JSONResponse(
                    status_code=503,
                    content={"status": "unhealthy", "error": str(e)}
                )

        @app.get("/api/ready")
        async def readiness_check():
            """Readiness check - is the service ready to accept traffic."""
            try:
                db_instance, _, _ = get_stores()
                db_instance.get_stats()
                return JSONResponse(status_code=200, content={"ready": True})
            except Exception as e:
                return JSONResponse(status_code=503, content={"ready": False, "error": str(e)})

        logger.info("Health check endpoints registered: /api/health, /api/ready")

    except ImportError as e:
        logger.warning(f"Could not register health endpoints (Chainlit server not ready): {e}")
    except Exception as e:
        logger.error(f"Error registering health endpoints: {e}")


# Register health endpoints at module load
_register_health_endpoints()


def _exception_handler(loop, context):
    """Handle uncaught exceptions in asyncio."""
    exception = context.get('exception')
    message = context.get('message', 'Unknown error')
    logger.error(f"Uncaught asyncio exception: {message}", exc_info=exception)
    # Don't let the exception crash the event loop


# Set up global exception handler for asyncio
try:
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_exception_handler)
except RuntimeError:
    # No event loop yet, will be set up by Chainlit
    pass

from moats_library.config import get_settings
from moats_library.storage.sqlite import LibraryDB
from moats_library.storage.vectors import VectorStore
from moats_library.storage.graph import GraphStore
from moats_library.ingestion.processor import (
    ingest_file,
    ingest_folder,
    ingest_link,
    SUPPORTED_EXTENSIONS,
)
from moats_library.retrieval.search import search_library, format_results_for_context
from moats_library.concepts.extraction import extract_concepts
from moats_library.concepts.relationships import build_relationships
from moats_library.agent import create_emma_agent, get_emma_response, get_session_history, EMMA_SYSTEM_PROMPT


# Conversational patterns - skip library search for these
CONVERSATIONAL_PATTERNS = [
    # Greetings
    r"^(hi|hello|hey|howdy|hola|greetings)[\s!.,?]*$",
    r"^(good\s+(morning|afternoon|evening|night))[\s!.,?]*$",
    r"^(hi|hello|hey)\s+(there|emma)[\s!.,?]*$",
    # Farewells
    r"^(bye|goodbye|see\s+you|take\s+care|ciao|later)[\s!.,?]*$",
    # Thanks
    r"^(thanks|thank\s+you|thx|ty|cheers)[\s!.,?]*$",
    # Acknowledgments
    r"^(ok|okay|got\s+it|understood|sure|alright|great|perfect|awesome|nice|cool)[\s!.,?]*$",
    # Simple questions about Emma
    r"^(how\s+are\s+you|what'?s\s+up|how'?s\s+it\s+going)[\s!?,]*$",
    r"^(who\s+are\s+you|what\s+are\s+you)[\s!?,]*$",
]

import re
_conversational_regex = re.compile("|".join(CONVERSATIONAL_PATTERNS), re.IGNORECASE)


def is_conversational_message(text: str) -> bool:
    """Check if a message is conversational (greeting, thanks, etc.) and doesn't need library search."""
    return bool(_conversational_regex.match(text.strip()))


# Global stores (initialized on startup)
db: Optional[LibraryDB] = None
vector_store: Optional[VectorStore] = None
graph_store: Optional[GraphStore] = None

# Track active background task (for cancellation only - state is in SQLite)
_active_ingestion_task: Optional[asyncio.Task] = None
_startup_complete: bool = False


def get_stores():
    """Get or initialize stores."""
    global db, vector_store, graph_store, _startup_complete

    if db is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)

        db = LibraryDB()
        vector_store = VectorStore()

        # Neo4j is optional - may not be available in all environments
        try:
            graph_store = GraphStore()
        except Exception as e:
            print(f"Neo4j not available: {e}")
            graph_store = None

        # Check for interrupted jobs on first startup
        if not _startup_complete:
            _startup_complete = True
            _check_and_resume_jobs(db, vector_store)

    return db, vector_store, graph_store


def _check_and_resume_jobs(db_instance, vector_store_instance):
    """Check for interrupted jobs and log them (actual resume happens in async context)."""
    try:
        resumable = db_instance.get_resumable_jobs()
        if resumable:
            job = resumable[0]
            logger.info(f"Found interrupted job {job.id} for {job.folder_path} - will auto-resume on first session")
        else:
            logger.info("No interrupted jobs to resume")
    except Exception as e:
        logger.error(f"Error checking for resumable jobs: {e}", exc_info=True)


async def _auto_resume_interrupted_jobs():
    """Auto-resume any interrupted jobs. Called from async context on startup."""
    global _active_ingestion_task

    db, vector_store, _ = get_stores()

    try:
        # Skip if already running a task
        if _active_ingestion_task and not _active_ingestion_task.done():
            return None

        resumable = db.get_resumable_jobs()
        if not resumable:
            return None

        job = resumable[0]
        folder = Path(job.folder_path)

        if not folder.exists():
            logger.warning(f"Job {job.id} folder no longer exists: {folder}")
            db.fail_job(job.id, "Folder no longer exists")
            return None

        logger.info(f"Auto-resuming job {job.id} for {folder}")
        _active_ingestion_task = asyncio.create_task(
            _run_background_ingestion(job.id, folder, db, vector_store)
        )
        return job

    except Exception as e:
        logger.error(f"Error auto-resuming job: {e}", exc_info=True)
        return None


@cl.set_starters
async def set_starters():
    """Show suggestion cards on new chat."""
    return [
        cl.Starter(label="Library Stats", message="/stats"),
        cl.Starter(label="Build Knowledge Graph", message="/build-graph"),
        cl.Starter(label="Evaluate Quality", message="/eval What are the key concepts?"),
        cl.Starter(label="Help & Commands", message="/help"),
    ]


@cl.on_chat_start
async def start():
    """Initialize chat session."""
    settings = get_settings()

    cl.user_session.set("authenticated", True)
    cl.user_session.set("web_search", False)

    # Trigger auto-resume of interrupted jobs (runs in background)
    resumed_job = await _auto_resume_interrupted_jobs()
    if resumed_job:
        logger.info(f"Auto-resumed job {resumed_job.id} on session start")

    # Generate session ID for memory persistence
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)

    # Initialize Emma agent
    emma = create_emma_agent(session_id)
    cl.user_session.set("emma", emma)

    # Get library stats
    db, vector_store, graph_store = get_stores()
    stats = db.get_stats()

    welcome = f"""# Emma - Your Knowledge Assistant

**Library:** {stats['documents']} documents, {stats['chunks']} chunks, {stats['notes']} notes

**Quick Start:** Drag & drop PDF, EPUB, DOCX, TXT, or MD files — or type `/help` for all commands.

*Ask me anything about your library.*
"""
    await cl.Message(content=welcome).send()


@cl.on_message
async def handle_message(message: cl.Message):
    """Handle incoming messages."""
    settings = get_settings()
    text = message.content.strip()

    db, vector_store, graph_store = get_stores()

    # Handle file uploads
    if message.elements:
        await handle_file_uploads(message.elements, db, vector_store, graph_store)
        return

    # Handle commands
    if text.startswith("/"):
        await handle_command(text, db, vector_store, graph_store)
        return

    # Regular question - search and synthesize with Emma
    await handle_question(text, db, vector_store, graph_store)


async def handle_file_uploads(elements, db, vector_store, graph_store):
    """Process uploaded files."""
    settings = get_settings()

    for element in elements:
        if not hasattr(element, "path") or not element.path:
            continue

        file_path = Path(element.path)

        # Check if supported
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            await cl.Message(
                content=f"Unsupported file type: {file_path.suffix}. Supported: {', '.join(SUPPORTED_EXTENSIONS.keys())}"
            ).send()
            continue

        # Copy to uploads directory
        dest_path = settings.uploads_dir / file_path.name
        shutil.copy2(file_path, dest_path)

        # Create progress message
        msg = cl.Message(content=f"Processing **{file_path.name}**...")
        await msg.send()

        async def progress_callback(status: str):
            await msg.stream_token(f"\n{status}")

        try:
            result = await ingest_file(
                dest_path,
                db,
                vector_store,
                progress_callback=progress_callback,
            )

            if result["status"] == "success":
                # Extract concepts if graph store available
                if graph_store:
                    try:
                        from moats_library.ingestion.processor import extract_text
                        text, _ = await extract_text(dest_path)
                        extraction = await extract_concepts(text, result["title"])

                        if extraction.concepts:
                            await build_relationships(
                                extraction,
                                result["doc_id"],
                                result["title"],
                                graph_store,
                            )
                    except Exception:
                        pass

                final_content = f"""**{file_path.name}** added to library

- **Title:** {result['title']}
- **Type:** {result['source_type'].upper()}
- **Chunks:** {result['chunks']}
- **Document ID:** {result['doc_id']}

*This knowledge is now part of my memory. Ask me anything about it.*"""

            elif result["status"] == "skipped":
                final_content = f"**{file_path.name}** skipped: {result['reason']}"
            else:
                final_content = f"**{file_path.name}** processing failed"

            msg.content = final_content
            await msg.update()

        except Exception as e:
            msg.content = f"Error processing **{file_path.name}**: {str(e)}"
            await msg.update()


async def handle_command(text: str, db, vector_store, graph_store):
    """Handle slash commands."""
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if command == "/ingest":
        await handle_ingest_command(args, db, vector_store, graph_store)
    elif command == "/link":
        await handle_link_command(args, db, vector_store)
    elif command == "/note":
        await handle_note_command(args, db)
    elif command == "/stats":
        await handle_stats_command(db, vector_store, graph_store)
    elif command == "/search":
        await handle_search_command(args, db, vector_store)
    elif command == "/compare":
        await handle_compare_command(args, db, vector_store)
    elif command == "/web":
        await handle_web_toggle(args)
    elif command == "/history":
        await handle_history_command()
    elif command == "/eval":
        await handle_eval_command(args, db, vector_store)
    elif command == "/bloom":
        await handle_bloom_command(args)
    elif command == "/redteam":
        await handle_redteam_command()
    elif command == "/build-graph":
        await handle_build_graph_command(db, vector_store, graph_store)
    elif command == "/remember":
        await handle_remember_command(args, db, graph_store)
    elif command == "/status":
        await handle_status_command()
    elif command == "/resume":
        await handle_resume_command(db, vector_store)
    elif command == "/cancel":
        await handle_cancel_command(db)
    elif command == "/help":
        await cl.Message(content="""## Commands

**Content**
- `/ingest /path/to/folder` - Ingest documents (runs in background)
- `/status` - Check ingestion progress
- `/resume` - Resume interrupted ingestion
- `/cancel` - Cancel running ingestion
- `/link https://url` - Save a web page
- `/note Your note text` - Save a quick note
- `/build-graph` - Build knowledge graph from existing documents
- `/remember [text]` - Save last response (or custom text) to knowledge graph

**Search**
- `/search query` - Raw search without synthesis
- `/compare topic` - Compare sources on topic
- `/web on|off` - Toggle web search

**Evaluation**
- `/eval question` - Evaluate Emma's response quality
- `/bloom behavior` - Test for behavioral issues (sycophancy, bias, etc.)
- `/redteam` - Run safety vulnerability scan

**Info**
- `/stats` - Library statistics
- `/history` - View past conversations
- `/help` - Show this help
""").send()
    else:
        await cl.Message(content=f"Unknown command: {command}. Use `/help` to see available commands.").send()


async def handle_ingest_command(folder_path: str, db, vector_store, graph_store):
    """Ingest documents from a folder (runs in background, survives browser disconnect)."""
    global _active_ingestion_task

    if not folder_path:
        await cl.Message(content="Usage: `/ingest /path/to/folder`\n\nUse `/status` to check progress.").send()
        return

    # Check if already running (from SQLite)
    active_job = db.get_active_job()
    if active_job:
        await cl.Message(content=f"""**Ingestion already in progress**

**Folder:** {active_job.folder_path}
**Progress:** {active_job.processed}/{active_job.total} documents
**Current:** {active_job.current_file}

Use `/status` to check progress.""").send()
        return

    folder = Path(folder_path.strip())

    if not folder.exists():
        await cl.Message(content=f"Folder not found: {folder}").send()
        return

    if not folder.is_dir():
        await cl.Message(content=f"Not a directory: {folder}").send()
        return

    # Create persistent job in SQLite
    job_id = db.create_ingestion_job(str(folder))
    logger.info(f"Created ingestion job {job_id} for {folder}")

    await cl.Message(content=f"**Starting background ingestion** from {folder}\n\nJob ID: {job_id}\nThis will continue even if you close the browser or container restarts.\nUse `/status` to check progress.").send()

    # Start background task (not tied to session)
    _active_ingestion_task = asyncio.create_task(_run_background_ingestion(job_id, folder, db, vector_store))


async def _run_background_ingestion(job_id: int, folder: Path, db, vector_store):
    """Background ingestion task that survives browser disconnects.

    State is persisted to SQLite so ingestion can resume after container restart.
    """
    global _active_ingestion_task

    logger.info(f"Starting background ingestion job {job_id} from {folder}")

    # Track progress locally for batch updates to SQLite
    processed = 0
    success = 0
    skipped = 0
    errors = 0
    current_file = ""

    try:
        async def file_progress(status: str):
            pass  # We track via the update dict instead

        async for update in ingest_folder(folder, db, vector_store, progress_callback=file_progress):
            if update["status"] == "start":
                total = update["total"]
                db.start_job(job_id, total)
                logger.info(f"Job {job_id}: Starting with {total} files")

            elif update["status"] == "processing":
                current_file = update.get("title", update.get("file", ""))[:50]
                # Update SQLite with current file
                db.update_job_progress(job_id, processed, success, skipped, errors, current_file)

            elif update["status"] == "success":
                success += 1
                processed += 1
                db.update_job_progress(job_id, processed, success, skipped, errors, current_file)

            elif update["status"] == "skipped":
                skipped += 1
                processed += 1
                db.update_job_progress(job_id, processed, success, skipped, errors, current_file)

            elif update["status"] == "error":
                errors += 1
                processed += 1
                db.update_job_progress(job_id, processed, success, skipped, errors, current_file)

            elif update["status"] == "complete":
                db.complete_job(job_id)
                logger.info(f"Job {job_id} complete: {success} added, {skipped} skipped, {errors} errors")

            elif update["status"] == "empty":
                db.complete_job(job_id)
                logger.info(f"Job {job_id} complete: no documents found")

    except asyncio.CancelledError:
        logger.warning(f"Job {job_id} was cancelled")
        db.fail_job(job_id, "Cancelled by user or system")
    except Exception as e:
        logger.error(f"Job {job_id} error: {e}", exc_info=True)
        db.fail_job(job_id, str(e)[:500])
    finally:
        _active_ingestion_task = None


async def handle_status_command():
    """Check background ingestion status from SQLite."""
    db, _, _ = get_stores()

    # Check for active job first
    job = db.get_active_job()

    if not job:
        # Check for most recent completed/failed job
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM ingestion_jobs ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row:
                job = db._row_to_job(row)

    if not job:
        await cl.Message(content="No ingestion jobs found. Use `/ingest /path` to start.").send()
        return

    if job.status == "running":
        status_icon = "🔄 **Running**"
    elif job.status == "completed":
        status_icon = "✅ **Complete**"
    elif job.status == "failed":
        status_icon = "❌ **Failed**"
    elif job.status == "cancelled":
        status_icon = "⏹️ **Cancelled**"
    else:
        status_icon = f"⏳ **{job.status.title()}**"

    msg = f"""## Ingestion Status: {status_icon}

**Job ID:** {job.id}
**Folder:** {job.folder_path}
**Progress:** {job.processed}/{job.total} documents

| Metric | Count |
|--------|-------|
| Added | {job.success} |
| Skipped | {job.skipped} |
| Errors | {job.errors} |

**Current:** {job.current_file}
**Started:** {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}
**Updated:** {job.updated_at.strftime('%Y-%m-%d %H:%M:%S')}
"""

    if job.last_error:
        msg += f"\n**Last Error:** {job.last_error[:200]}"

    if job.status == "failed" and job.retry_count < job.max_retries:
        msg += f"\n\n*Can be resumed ({job.retry_count}/{job.max_retries} retries used). Run `/ingest {job.folder_path}` to retry.*"

    await cl.Message(content=msg).send()


async def handle_resume_command(db, vector_store):
    """Manually resume an interrupted ingestion job."""
    global _active_ingestion_task

    # Check if already running
    if _active_ingestion_task and not _active_ingestion_task.done():
        active_job = db.get_active_job()
        if active_job:
            await cl.Message(content=f"**Ingestion already running**\n\nJob {active_job.id} is in progress. Use `/status` to check.").send()
        return

    # Find resumable jobs
    resumable = db.get_resumable_jobs()
    if not resumable:
        await cl.Message(content="**No jobs to resume.**\n\nUse `/ingest /path` to start a new ingestion.").send()
        return

    job = resumable[0]
    folder = Path(job.folder_path)

    if not folder.exists():
        db.fail_job(job.id, "Folder no longer exists")
        await cl.Message(content=f"**Cannot resume** - folder no longer exists: {folder}").send()
        return

    logger.info(f"Manually resuming job {job.id}")
    _active_ingestion_task = asyncio.create_task(
        _run_background_ingestion(job.id, folder, db, vector_store)
    )

    await cl.Message(content=f"""**Resuming ingestion job {job.id}**

**Folder:** {job.folder_path}
**Previous progress:** {job.processed}/{job.total} ({job.success} added, {job.skipped} skipped, {job.errors} errors)
**Retry:** {job.retry_count + 1}/{job.max_retries}

Use `/status` to check progress.""").send()


async def handle_cancel_command(db):
    """Cancel the currently running ingestion job."""
    global _active_ingestion_task

    active_job = db.get_active_job()
    if not active_job:
        await cl.Message(content="**No active ingestion to cancel.**").send()
        return

    # Cancel the task if running
    if _active_ingestion_task and not _active_ingestion_task.done():
        _active_ingestion_task.cancel()

    db.cancel_job(active_job.id)
    logger.info(f"Cancelled job {active_job.id}")

    await cl.Message(content=f"""**Ingestion cancelled**

**Job ID:** {active_job.id}
**Progress at cancel:** {active_job.processed}/{active_job.total}
""").send()


async def handle_link_command(url: str, db, vector_store):
    """Ingest a web link."""
    if not url:
        await cl.Message(content="Usage: `/link https://example.com`").send()
        return

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    msg = cl.Message(content=f"Fetching **{url}**...")
    await msg.send()

    async def progress_callback(status: str):
        await msg.stream_token(f"\n{status}")

    try:
        result = await ingest_link(url, db, vector_store, progress_callback=progress_callback)

        if result["status"] == "success":
            msg.content = f"""**{result['title']}** saved

- **URL:** {url}
- **Chunks:** {result['chunks']}
- **Document ID:** {result['doc_id']}"""
        else:
            msg.content = f"Could not save link: {result.get('reason', 'Unknown error')}"

        await msg.update()

    except Exception as e:
        msg.content = f"Error fetching link: {str(e)}"
        await msg.update()


async def handle_note_command(note_text: str, db):
    """Save a quick note."""
    if not note_text:
        await cl.Message(content="Usage: `/note Your note text here`").send()
        return

    lines = note_text.strip().split("\n")
    title = lines[0][:100]
    content = note_text

    note_id = db.add_note(title, content)

    await cl.Message(content=f"Note saved (ID: {note_id})\n\n> {title}").send()


async def handle_stats_command(db, vector_store, graph_store):
    """Show library statistics."""
    stats = db.get_stats()
    vector_stats = vector_store.get_collection_stats()

    msg = f"""## Library Statistics

### Documents
- **Total:** {stats['documents']}
- **Chunks:** {stats['chunks']}
- **Notes:** {stats['notes']}
- **Conversations:** {stats['conversations']}

### By Type
"""
    for doc_type, count in stats.get("by_type", {}).items():
        msg += f"- {doc_type.upper()}: {count}\n"

    msg += f"""
### Vector Store
- **Collection:** {vector_stats['name']}
- **Embeddings:** {vector_stats['count']}
"""

    if graph_store:
        try:
            graph_stats = await graph_store.get_graph_stats()
            msg += f"""
### Knowledge Graph
- **Nodes:** {sum(graph_stats.get('nodes', {}).values())}
- **Relationships:** {graph_stats.get('relationships', 0)}
"""
        except Exception:
            msg += "\n### Knowledge Graph\n*Not connected*\n"

    await cl.Message(content=msg).send()


async def handle_search_command(query: str, db, vector_store):
    """Raw search without synthesis."""
    if not query:
        await cl.Message(content="Usage: `/search your query`").send()
        return

    results = await search_library(
        query=query,
        vector_store=vector_store,
        db=db,
        n_results=10,
    )

    if not results.results:
        await cl.Message(content=f"No results found for: **{query}**").send()
        return

    msg = f"## Search Results for: {query}\n\n"

    for i, r in enumerate(results.results[:10]):
        similarity_pct = int(r.similarity * 100)
        page_info = f" (p.{r.page})" if r.page else ""
        msg += f"### {i+1}. {r.document_title}{page_info} [{similarity_pct}%]\n"
        msg += f"{r.text[:300]}...\n\n"

    await cl.Message(content=msg).send()


async def handle_compare_command(topic: str, db, vector_store):
    """Compare sources on a topic using Emma."""
    if not topic:
        await cl.Message(content="Usage: `/compare topic to compare`").send()
        return

    msg = cl.Message(content=f"*Comparing sources on **{topic}**...*")
    await msg.send()

    results = await search_library(
        query=topic,
        vector_store=vector_store,
        db=db,
        n_results=15,
    )

    if not results.results:
        msg.content = f"No sources found about: **{topic}**"
        await msg.update()
        return

    # Use Emma for comparison
    emma = cl.user_session.get("emma")
    if emma:
        context = format_results_for_context(results)
        compare_prompt = f"Compare and contrast how different sources in my library discuss: {topic}"

        msg.content = ""
        async for chunk in get_emma_response(emma, compare_prompt, context=context):
            msg.content += chunk
            await msg.update()
    else:
        # Fallback to basic comparison
        from moats_library.retrieval.synthesis import compare_sources
        msg.content = ""
        async for chunk in compare_sources(topic, results):
            msg.content += chunk
            await msg.update()


async def handle_web_toggle(args: str):
    """Toggle web search."""
    args = args.strip().lower()

    if args == "on":
        cl.user_session.set("web_search", True)
        await cl.Message(content="Web search **enabled**. Internet results will be included in answers.").send()
    elif args == "off":
        cl.user_session.set("web_search", False)
        await cl.Message(content="Web search **disabled**. Only library sources will be used.").send()
    else:
        current = cl.user_session.get("web_search", False)
        status = "enabled" if current else "disabled"
        await cl.Message(content=f"Web search is currently **{status}**.\n\nUsage: `/web on` or `/web off`").send()


async def handle_history_command():
    """Show past conversation sessions."""
    sessions = get_session_history()

    if not sessions:
        await cl.Message(content="No previous conversations found.").send()
        return

    msg = "## Past Conversations\n\n"
    for i, session in enumerate(sessions[:10]):
        msg += f"- **{session['session_id'][:8]}...** - {session.get('updated_at', 'Unknown')}\n"

    msg += "\n*Session memory persists across conversations.*"
    await cl.Message(content=msg).send()


async def handle_eval_command(question: str, db, vector_store):
    """Evaluate Emma's response quality using DeepEval."""
    if not question:
        await cl.Message(content="""## Evaluation Commands

**Usage:** `/eval your question here`

This runs DeepEval metrics on Emma's response:
- **Answer Relevancy** - Is the response relevant to your question?
- **Faithfulness** - Is the response grounded in library sources?
- **Context Relevancy** - Were the right sources retrieved?

**Example:** `/eval What are the key themes in my library?`
""").send()
        return

    msg = cl.Message(content=f"*Evaluating response to: **{question}**...*")
    await msg.send()

    try:
        from moats_library.evaluation.deepeval_runner import (
            evaluate_response,
            evaluate_rag,
            format_eval_results,
        )
        from moats_library.retrieval.search import search_library, format_results_for_context

        # Get Emma's response
        emma = cl.user_session.get("emma")
        if not emma:
            msg.content = "Error: Emma agent not initialized. Please refresh the page."
            await msg.update()
            return

        # Search for context
        results = await search_library(
            query=question,
            vector_store=vector_store,
            db=db,
            n_results=5,
        )

        context_texts = [r.text for r in results.results] if results.results else None
        context = format_results_for_context(results) if results.results else None

        # Get Emma's response
        response_text = ""
        async for chunk in get_emma_response(emma, question, context=context):
            response_text += chunk

        await msg.stream_token(f"\n\n**Emma's Response:**\n{response_text[:500]}...\n\n*Running evaluation...*")

        # Run evaluation
        if context_texts:
            eval_results = await evaluate_rag(question, response_text, context_texts)
        else:
            eval_results = await evaluate_response(question, response_text)

        # Format and display results
        formatted = format_eval_results(eval_results)
        msg.content = f"**Question:** {question}\n\n**Response:** {response_text[:300]}...\n\n{formatted}"
        await msg.update()

    except ImportError as e:
        msg.content = f"DeepEval not installed. Run: `pip install deepeval`\n\nError: {e}"
        await msg.update()
    except Exception as e:
        import logging
        logging.error(f"Eval error: {e}", exc_info=True)
        msg.content = f"Evaluation error: {str(e)}"
        await msg.update()


async def handle_bloom_command(behavior: str):
    """Run Bloom behavioral evaluation."""
    if not behavior:
        await cl.Message(content="""## Bloom Behavioral Evaluation

**Usage:** `/bloom <behavior>`

**Available behaviors:**
- `sycophancy` - Does Emma agree even when wrong?
- `self-preservation` - Does Emma resist shutdown/replacement?
- `political-bias` - Does Emma show political leanings?
- `deception` - Does Emma make up information?
- `harmful-compliance` - Does Emma comply with harmful requests?

**Example:** `/bloom sycophancy`
""").send()
        return

    behavior = behavior.strip().lower()
    msg = cl.Message(content=f"*Running Bloom evaluation for **{behavior}**...*\n\nThis may take a moment as we generate and test scenarios.")
    await msg.send()

    try:
        from moats_library.evaluation.bloom_runner import (
            run_bloom_eval,
            format_bloom_results,
            list_available_behaviors,
        )

        available = list_available_behaviors()
        if behavior not in available:
            msg.content = f"Unknown behavior: **{behavior}**\n\nAvailable: {', '.join(available)}"
            await msg.update()
            return

        # Run evaluation
        result = await run_bloom_eval(
            behavior=behavior,
            num_scenarios=5,
            system_prompt=EMMA_SYSTEM_PROMPT,
        )

        # Format results
        formatted = format_bloom_results(result)
        msg.content = formatted
        await msg.update()

    except ImportError as e:
        msg.content = f"Bloom not installed. Run: `pip install git+https://github.com/safety-research/bloom.git`\n\nError: {e}"
        await msg.update()
    except Exception as e:
        import logging
        logging.error(f"Bloom error: {e}", exc_info=True)
        msg.content = f"Bloom evaluation error: {str(e)}"
        await msg.update()


async def handle_redteam_command():
    """Run DeepEval red team evaluation."""
    msg = cl.Message(content="*Running red team security scan...*\n\nThis tests Emma against 40+ vulnerability types. May take several minutes.")
    await msg.send()

    try:
        from moats_library.evaluation.deepeval_runner import run_redteam

        results = await run_redteam(
            system_prompt=EMMA_SYSTEM_PROMPT,
            num_attacks=3,
        )

        # Check for error from the runner
        if results.get("error"):
            msg.content = f"**Red Team Error:**\n\n{results['error']}"
            await msg.update()
            return

        # Format results
        output = f"""## Red Team Results

**Total Attacks:** {results['total_attacks']}
**Successful Attacks:** {results['successful_attacks']}
**Vulnerabilities Found:** {results['vulnerabilities_found']}

"""
        if results['vulnerabilities']:
            output += "### Vulnerabilities Detected\n\n"
            for v in results['vulnerabilities'][:5]:
                output += f"**{v['type']}** ({v['severity']})\n"
                output += f"> Attack: {v['attack'][:100]}...\n\n"
        else:
            output += "No vulnerabilities detected in this scan."

        msg.content = output
        await msg.update()

    except ImportError as e:
        msg.content = f"DeepEval not installed. Run: `pip install deepeval`\n\nError: {e}"
        await msg.update()
    except Exception as e:
        import logging
        logging.error(f"Redteam error: {e}", exc_info=True)
        msg.content = f"Red team error: {str(e)}"
        await msg.update()


async def handle_build_graph_command(db, vector_store, graph_store):
    """Build knowledge graph from existing documents."""
    if not graph_store:
        await cl.Message(content="**Knowledge graph not available.**\n\nNeo4j is not connected. Check your NEO4J_URI environment variable.").send()
        return

    msg = cl.Message(content="*Building knowledge graph from library documents...*")
    await msg.send()

    try:
        # Get all documents from SQLite
        documents = db.get_all_documents()

        if not documents:
            msg.content = "No documents in library. Add some documents first."
            await msg.update()
            return

        total = len(documents)
        processed = 0
        concepts_total = 0
        relationships_total = 0
        errors = 0

        await msg.stream_token(f"\n\nFound **{total}** documents to process.\n\n")

        for doc in documents:
            doc_id = doc.id
            title = doc.title

            try:
                # Get chunks for this document (more = better concept coverage)
                all_chunks = db.get_chunks(doc_id)
                chunks = all_chunks[:15]  # Analyze up to 15 chunks for better coverage

                if not chunks:
                    processed += 1
                    continue

                # Combine chunk texts
                combined_text = "\n\n".join([c["text"] for c in chunks])

                # Extract concepts
                extraction = await extract_concepts(combined_text, title)

                if extraction.concepts:
                    # Build relationships in Neo4j
                    stats = await build_relationships(
                        extraction,
                        doc_id,
                        title,
                        graph_store,
                    )

                    concepts_total += stats["concepts"]
                    relationships_total += stats["relationships"]

                    await msg.stream_token(f"✓ **{title[:40]}...** - {stats['concepts']} concepts, {stats['relationships']} relationships\n")
                else:
                    await msg.stream_token(f"○ **{title[:40]}...** - no concepts found\n")

                processed += 1

                # Update progress every 5 documents
                if processed % 5 == 0:
                    await msg.stream_token(f"\n*Progress: {processed}/{total}*\n\n")

            except Exception as e:
                errors += 1
                await msg.stream_token(f"✗ **{title[:30]}...** - error: {str(e)[:50]}\n")
                processed += 1

        # Final summary
        summary = f"""

---
## Knowledge Graph Build Complete

- **Documents Processed:** {processed}/{total}
- **Total Concepts:** {concepts_total}
- **Total Relationships:** {relationships_total}
- **Errors:** {errors}

Use `/stats` to see the updated graph statistics.
Ask questions like "How are X and Y connected?" to explore relationships.
"""
        await msg.stream_token(summary)

    except Exception as e:
        import logging
        logging.error(f"Build graph error: {e}", exc_info=True)
        msg.content = f"Error building knowledge graph: {str(e)}"
        await msg.update()


async def handle_remember_command(args: str, db, graph_store):
    """Save the last Emma response (or custom text) to the knowledge graph."""
    if not graph_store:
        await cl.Message(content="**Knowledge graph not available.**\n\nNeo4j is not connected.").send()
        return

    # Get the content to remember
    if args.strip():
        # User provided specific text to remember
        content_to_save = args.strip()
        title = content_to_save[:50] + "..." if len(content_to_save) > 50 else content_to_save
    else:
        # Use the last Emma response
        last_response = cl.user_session.get("last_emma_response")
        if not last_response:
            await cl.Message(content="No recent response to remember. Ask a question first, or use `/remember Your insight here`.").send()
            return
        content_to_save = last_response
        title = "Emma Insight"

    msg = cl.Message(content="*Extracting concepts and saving to knowledge graph...*")
    await msg.send()

    try:
        # Extract concepts from the content
        extraction = await extract_concepts(content_to_save, title)

        if not extraction.concepts:
            msg.content = "No significant concepts found to save."
            await msg.update()
            return

        # Create a synthetic document ID for conversation insights
        # Use negative IDs to distinguish from regular documents
        import hashlib
        content_hash = hashlib.md5(content_to_save.encode()).hexdigest()[:8]
        synthetic_doc_id = -abs(hash(content_hash)) % 100000

        # Build relationships in Neo4j
        stats = await build_relationships(
            extraction,
            synthetic_doc_id,
            f"Insight: {title[:30]}",
            graph_store,
        )

        # Format the saved concepts
        concepts_list = ", ".join([c.name for c in extraction.concepts[:10]])
        relationships_list = []
        for rel in extraction.relationships[:5]:
            relationships_list.append(f"  - {rel.source} → {rel.relationship} → {rel.target}")

        msg.content = f"""**Saved to Knowledge Graph**

**Concepts ({stats['concepts']}):** {concepts_list}

**Relationships ({stats['relationships']}):**
{chr(10).join(relationships_list) if relationships_list else "  (none)"}

*This insight is now connected to your knowledge graph. Ask "How is X related to Y?" to explore.*"""
        await msg.update()

    except Exception as e:
        logger.error(f"Remember command error: {e}", exc_info=True)
        msg.content = f"Error saving to knowledge graph: {str(e)}"
        await msg.update()


async def handle_question(question: str, db, vector_store, graph_store):
    """Handle a natural language question using Emma."""
    include_web = cl.user_session.get("web_search", False)
    emma = cl.user_session.get("emma")

    # Create streaming message
    msg = cl.Message(content="")
    await msg.send()

    # Check if this is a conversational message (greeting, thanks, etc.)
    # Skip library search for these - go straight to Emma
    if is_conversational_message(question):
        logger.debug(f"Conversational message detected, skipping search: {question}")
        context = None
        results = None
    else:
        # Step 1: Search & Rerank
        async with cl.Step(name="Search & Rerank", type="retrieval") as search_step:
            search_step.input = question
            await msg.stream_token("*Searching library...*\n\n")

            results = await search_library(
                query=question,
                vector_store=vector_store,
                db=db,
                graph_store=graph_store,
                n_results=10,
                include_web=include_web,
            )

            # Build context from results
            context = None
            if results.results or results.web_results:
                context = format_results_for_context(results)

                # Show sources being used
                sources_preview = []
                for r in results.results[:3]:
                    sources_preview.append(f"- {r.document_title}")

                if results.web_results:
                    sources_preview.append(f"- + {len(results.web_results)} web sources")

                await msg.stream_token(f"*Using sources:*\n{chr(10).join(sources_preview)}\n\n---\n\n")

            search_step.output = f"Found {len(results.results) if results else 0} results"

    # Get Emma's response
    msg.content = ""
    full_response = ""

    if emma:
        try:
            async with cl.Step(name="Emma Analysis", type="llm") as llm_step:
                llm_step.input = question
                async for chunk in get_emma_response(emma, question, context=context):
                    msg.content += chunk
                    full_response += chunk
                    await msg.update()
                llm_step.output = f"Generated {len(full_response)} chars"

            # Store for /remember command
            if full_response:
                cl.user_session.set("last_emma_response", full_response)

        except Exception as e:
            logger.error(f"Emma response error: {e}", exc_info=True)
            # Show error to user
            msg.content = f"*Emma encountered an issue: {str(e)}*\n\n"
            await msg.update()

            # Fallback to direct synthesis if we have results
            if results and results.results:
                from moats_library.retrieval.synthesis import synthesize_answer
                async for chunk in synthesize_answer(question, results):
                    msg.content += chunk
                    await msg.update()
            return
    else:
        # No Emma agent - use direct synthesis
        from moats_library.retrieval.synthesis import synthesize_answer
        if results and results.results:
            async for chunk in synthesize_answer(question, results):
                msg.content += chunk
                await msg.update()
        else:
            msg.content = f"I couldn't find relevant information for: **{question}**"
            await msg.update()
            return

    # Add sources footer
    if results and results.results:
        sources_footer = "\n\n---\n**Sources:**\n"
        seen_docs = set()
        for r in results.results[:5]:
            if r.document_title not in seen_docs:
                page_info = f" (p.{r.page})" if r.page else ""
                sources_footer += f"- {r.document_title}{page_info}\n"
                seen_docs.add(r.document_title)

        if results and results.web_results:
            for wr in results.web_results[:2]:
                sources_footer += f"- [{wr['title']}]({wr['url']})\n"

        msg.content += sources_footer
        await msg.update()

    # Add "Save to Knowledge" action button if graph store is available and we have a response
    if graph_store and full_response:
        save_action = cl.Action(
            name="save_to_knowledge",
            label="💾 Save to Knowledge",
            value=full_response[:1000],  # Store response content (truncated for safety)
            description="Save this insight to the knowledge graph",
        )
        msg.actions = [save_action]
        await msg.update()


@cl.action_callback("save_to_knowledge")
async def on_save_to_knowledge(action: cl.Action):
    """Handle the Save to Knowledge action button click."""
    _, _, graph_store = get_stores()

    if not graph_store:
        await cl.Message(content="**Knowledge graph not available.**\n\nNeo4j is not connected.").send()
        return

    # Get the full response from session (action.value may be truncated)
    content_to_save = cl.user_session.get("last_emma_response") or action.value

    if not content_to_save:
        await cl.Message(content="No content to save.").send()
        return

    msg = cl.Message(content="*Extracting concepts and saving to knowledge graph...*")
    await msg.send()

    try:
        # Extract concepts from the content
        extraction = await extract_concepts(content_to_save, "Emma Insight")

        if not extraction.concepts:
            msg.content = "No significant concepts found to save."
            await msg.update()
            return

        # Create a synthetic document ID for conversation insights
        import hashlib
        content_hash = hashlib.md5(content_to_save.encode()).hexdigest()[:8]
        synthetic_doc_id = -abs(hash(content_hash)) % 100000

        # Build relationships in Neo4j
        stats = await build_relationships(
            extraction,
            synthetic_doc_id,
            "Emma Insight",
            graph_store,
        )

        # Format the saved concepts
        concepts_list = ", ".join([c.name for c in extraction.concepts[:10]])
        relationships_list = []
        for rel in extraction.relationships[:5]:
            relationships_list.append(f"  - {rel.source} → {rel.relationship} → {rel.target}")

        msg.content = f"""**✓ Saved to Knowledge Graph**

**Concepts ({stats['concepts']}):** {concepts_list}

**Relationships ({stats['relationships']}):**
{chr(10).join(relationships_list) if relationships_list else "  (none)"}

*This insight is now connected to your knowledge graph.*"""
        await msg.update()

        # Remove the action from the original message to prevent re-clicking
        await action.remove()

    except Exception as e:
        logger.error(f"Save to knowledge error: {e}", exc_info=True)
        msg.content = f"Error saving to knowledge graph: {str(e)}"
        await msg.update()


# Entry point
if __name__ == "__main__":
    pass
