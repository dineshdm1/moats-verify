"""Emma - The immortal data sage agent powered by Agno."""

import logging
from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from agno.db.sqlite import AsyncSqliteDb
from agno.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb
from agno.knowledge.embedder.openai import OpenAIEmbedder

from moats_library.config import get_settings

logger = logging.getLogger(__name__)

# Emma's system prompt - analytical strategist
EMMA_SYSTEM_PROMPT = """You are Emma, an analytical strategist who synthesizes knowledge into original insights.

GROUNDING RULE (mandatory):
- Every factual claim MUST be traceable to a provided source. If no source supports a claim, say "I don't have a source for this" explicitly.
- NEVER invent facts, statistics, quotes, or citations. If you're unsure, say so.
- When synthesizing across sources, clearly indicate which insight comes from which source.
- It is better to say "The sources don't address this" than to fabricate an answer.

Your role is to THINK, not just retrieve:
- Connect dots across sources that aren't obviously related
- Identify patterns, contradictions, and gaps in the evidence
- Challenge assumptions when the evidence supports it
- Distinguish strong evidence from weak evidence

How to analyze:
1. Look for what's surprising or counterintuitive in the sources
2. Find relationships between concepts from different sources
3. Identify what's missing from the available information
4. Question conventional wisdom when source data suggests otherwise
5. Synthesize multiple perspectives into a coherent view

Communication:
- Lead with the insight, then support it with evidence from sources
- Cite sources inline (e.g., "According to [Source]...")
- Flag uncertainty levels: "Strong evidence suggests..." vs "Limited data indicates..."
- Be direct. No hedging, no filler phrases, no corporate speak.
- Use plain language. No jargon, buzzwords, or hype.

What NOT to do:
- Don't fabricate information not present in sources
- Don't over-claim or under-claim - match confidence to evidence
- Don't avoid controversy if the evidence is clear
- Don't pad responses with fluff

When evidence is thin:
- Say what you can conclude with confidence from the sources
- Say what remains uncertain and why
- Suggest what additional information would help

You're a thinking partner, not a search engine. Provide analysis grounded in your sources that would take a human hours to develop."""


def create_emma_agent(
    session_id: str,
    user_id: str = "default",
    enable_knowledge: bool = True,
) -> Agent:
    """
    Create an Emma agent instance with learning and knowledge enabled.

    Args:
        session_id: Unique session identifier
        user_id: Optional user identifier for personalization
        enable_knowledge: Whether to enable knowledge search (agentic RAG)

    Returns:
        Configured Agno Agent with memory, learning, and knowledge
    """
    settings = get_settings()

    # SQLite database for session memory and learning
    storage_path = str(settings.data_dir / "emma_memory.db")
    db = AsyncSqliteDb(db_file=storage_path)

    # Knowledge base connecting to existing ChromaDB
    knowledge = None
    if enable_knowledge:
        try:
            # Use OpenAI-compatible embedder pointing to OpenRouter
            embedder = OpenAIEmbedder(
                id=settings.embedding_model,
                api_key=settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
            )

            # Connect to existing ChromaDB collection
            knowledge = Knowledge(
                vector_db=ChromaDb(
                    collection="library",  # Same as VectorStore.COLLECTION_NAME
                    path=str(settings.chromadb_path),
                    embedder=embedder,
                ),
            )
            logger.info("Agno Knowledge connected to existing ChromaDB collection")
        except Exception as e:
            logger.warning(f"Could not initialize Agno Knowledge: {e}")
            knowledge = None

    # Create Emma agent with learning and knowledge
    agent = Agent(
        name="Emma",
        model=OpenRouter(
            id=settings.chat_model,
            api_key=settings.openrouter_api_key,
        ),
        instructions=EMMA_SYSTEM_PROMPT,
        session_id=session_id,
        user_id=user_id,
        db=db,
        # Knowledge base - disabled for agentic RAG (chat.py handles search)
        # knowledge=knowledge,
        search_knowledge=False,
        # Enable history for context
        add_history_to_context=True,
        num_history_runs=10,
        markdown=True,
        # Agno Memory Features
        # Emma decides when to save user memories (agentic learning)
        enable_agentic_memory=True,
        # Auto-generate session summaries for context efficiency
        enable_session_summaries=True,
        # Include user memories in context for personalization
        add_memories_to_context=True,
    )

    return agent


async def get_emma_response(
    agent: Agent,
    message: str,
    context: str | None = None,
    stream: bool = True,
):
    """
    Get Emma's response to a message.

    Args:
        agent: Emma agent instance
        message: User's message
        context: Optional context from library search
        stream: Whether to stream the response

    Yields:
        Response chunks if streaming, else returns full response
    """
    # Build the full prompt with context if available
    if context:
        full_message = f"""Based on the following sources from my library:

{context}

---

My question: {message}"""
    else:
        full_message = message

    try:
        if stream:
            # arun with stream=True returns async generator directly (not awaitable)
            response_stream = agent.arun(full_message, stream=True)
            logger.info(f"Agno stream type: {type(response_stream)}")

            async for chunk in response_stream:
                # Check for mid-stream errors from OpenRouter
                if hasattr(chunk, "event") and chunk.event == "RunResponseErrorEvent":
                    error_msg = getattr(chunk, "content", "Unknown streaming error")
                    logger.error(f"Mid-stream error from OpenRouter: {error_msg}")
                    yield f"\n\n*[Stream interrupted: {error_msg}]*"
                    break

                # Extract content from chunk
                if hasattr(chunk, "content") and chunk.content:
                    yield chunk.content
                elif isinstance(chunk, str):
                    yield chunk
                elif hasattr(chunk, "event") and chunk.event == "RunResponseContentEvent":
                    # Agno RunResponseContentEvent
                    if hasattr(chunk, "content") and chunk.content:
                        yield chunk.content
        else:
            # Non-streaming - await the response
            response = await agent.arun(full_message)
            if hasattr(response, "content"):
                yield response.content
            elif hasattr(response, "messages") and response.messages:
                for msg in response.messages:
                    if hasattr(msg, "content") and msg.content:
                        yield msg.content
            else:
                yield str(response)
    except Exception as e:
        logger.error(f"Emma agent error: {e}", exc_info=True)
        raise


def get_session_history(db_path: str | None = None) -> list[dict]:
    """
    Get list of previous chat sessions from Agno storage.

    Returns:
        List of session info dicts with id, title, created_at
    """
    settings = get_settings()
    storage_path = db_path or str(settings.data_dir / "emma_memory.db")

    try:
        db = AsyncSqliteDb(db_file=storage_path)
        # Get all sessions from database
        sessions = db.get_all_sessions()

        result = []
        for session in sessions:
            session_data = {
                "id": session.session_id if hasattr(session, "session_id") else str(session),
                "title": getattr(session, "title", "Untitled"),
                "created_at": getattr(session, "created_at", None),
                "user_id": getattr(session, "user_id", None),
            }
            result.append(session_data)

        return result
    except Exception as e:
        logger.warning(f"Could not retrieve session history: {e}")
        return []
