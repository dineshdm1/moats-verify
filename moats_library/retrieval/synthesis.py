"""Answer synthesis from retrieved sources."""

from typing import AsyncIterator
import httpx
import json

from moats_library.config import get_settings
from moats_library.retrieval.search import SearchResults, format_results_for_context


async def synthesize_answer(
    query: str,
    results: SearchResults,
    stream: bool = True,
) -> AsyncIterator[str]:
    """
    Synthesize an answer from search results using the LLM.

    Args:
        query: User's question
        results: Search results with context
        stream: Whether to stream the response

    Yields:
        Answer text chunks
    """
    settings = get_settings()

    if not settings.openrouter_api_key:
        yield "Error: OPENROUTER_API_KEY not configured."
        return

    # Format context
    context = format_results_for_context(results)

    # Build prompt
    system_prompt = """You are a knowledgeable research assistant helping users explore their personal knowledge library.

Your task is to synthesize information from the provided sources to answer the user's question.

Guidelines:
- Provide accurate, well-reasoned answers based on the sources
- Cite sources by their titles when referencing specific information
- If sources contain conflicting information, acknowledge it
- If the sources don't contain enough information, say so clearly
- Be concise but thorough
- Use markdown formatting for readability"""

    user_prompt = f"""Based on the following sources from my library, please answer this question:

**Question:** {query}

---
## Sources

{context}
---

Please synthesize an answer from these sources. Cite specific sources when relevant."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Stream response from OpenRouter
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.chat_model,
                "messages": messages,
                "stream": True,
                "temperature": 0.7,
                "max_tokens": 2000,
            },
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue

                data = line[6:]  # Remove "data: " prefix
                if data == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue


async def generate_summary(
    text: str,
    max_length: int = 500,
) -> str:
    """
    Generate a summary of text.
    """
    settings = get_settings()

    if not settings.openrouter_api_key:
        return text[:max_length] + "..." if len(text) > max_length else text

    prompt = f"""Summarize the following text in {max_length} characters or less:

{text[:4000]}

Provide a concise summary that captures the key points."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.chat_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
                "max_tokens": 500,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def compare_sources(
    topic: str,
    results: SearchResults,
) -> AsyncIterator[str]:
    """
    Compare perspectives from different sources on a topic.
    """
    settings = get_settings()

    if not results.results:
        yield "No sources found to compare."
        return

    # Group by document
    by_document: dict[str, list[str]] = {}
    for r in results.results:
        if r.document_title not in by_document:
            by_document[r.document_title] = []
        by_document[r.document_title].append(r.text)

    context_parts = []
    for doc_title, chunks in by_document.items():
        combined = "\n".join(chunks[:3])  # First 3 chunks per document
        context_parts.append(f"## {doc_title}\n{combined}")

    context = "\n\n---\n\n".join(context_parts)

    prompt = f"""Compare and contrast how different sources in my library discuss this topic:

**Topic:** {topic}

---
## Sources

{context}
---

Please analyze:
1. Key similarities in how sources discuss this topic
2. Notable differences or unique perspectives
3. Any contradictions or debates between sources
4. Overall synthesis of the different viewpoints"""

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.chat_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "temperature": 0.7,
            },
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue

                data = line[6:]
                if data == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue
