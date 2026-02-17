"""Concept extraction from documents using LLM."""

import json
import httpx
from dataclasses import dataclass

from moats_library.config import get_settings


@dataclass
class ExtractedConcept:
    """An extracted concept from a document."""

    name: str
    type: str  # 'person', 'concept', 'theory', 'method', 'organization', 'topic'
    description: str | None = None


@dataclass
class ExtractionResult:
    """Result of concept extraction."""

    concepts: list[ExtractedConcept]
    topics: list[str]
    authors: list[str]
    relationships: list[tuple[str, str, str]]  # (from, relationship, to)


async def extract_concepts(
    text: str,
    document_title: str,
    max_concepts: int = 20,
) -> ExtractionResult:
    """
    Extract concepts, topics, and relationships from text using LLM.

    Args:
        text: Text to analyze (will be truncated if too long)
        document_title: Title of the source document
        max_concepts: Maximum number of concepts to extract

    Returns:
        ExtractionResult with extracted entities
    """
    settings = get_settings()

    if not settings.openrouter_api_key:
        return ExtractionResult(concepts=[], topics=[], authors=[], relationships=[])

    # Truncate text to reasonable size for LLM
    truncated = text[:8000] if len(text) > 8000 else text

    prompt = f"""Analyze this text from "{document_title}" and extract key concepts.

TEXT:
{truncated}

---

Extract and return as JSON:
{{
    "concepts": [
        {{"name": "Concept Name", "type": "concept|person|theory|method|organization", "description": "Brief description"}}
    ],
    "topics": ["topic1", "topic2"],
    "authors": ["Author Name"],
    "relationships": [
        ["Concept A", "relates_to", "Concept B"],
        ["Theory X", "proposed_by", "Person Y"]
    ]
}}

Guidelines:
- Extract 5-{max_concepts} key concepts depending on text complexity
- Include people, theories, methodologies, organizations mentioned
- Topics should be broad categories the text covers
- Authors are people who wrote or are credited in the text
- Relationships show connections between extracted concepts

Return ONLY valid JSON, no explanation."""

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": settings.app_url,
                    "X-Title": settings.app_name,
                },
                json={
                    "model": settings.chat_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]

            # Parse JSON from response
            # Handle markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            parsed = json.loads(content.strip())

            concepts = [
                ExtractedConcept(
                    name=c.get("name", ""),
                    type=c.get("type", "concept"),
                    description=c.get("description"),
                )
                for c in parsed.get("concepts", [])
                if c.get("name")
            ]

            relationships = [
                (r[0], r[1], r[2])
                for r in parsed.get("relationships", [])
                if len(r) == 3
            ]

            return ExtractionResult(
                concepts=concepts,
                topics=parsed.get("topics", []),
                authors=parsed.get("authors", []),
                relationships=relationships,
            )

    except Exception as e:
        return ExtractionResult(concepts=[], topics=[], authors=[], relationships=[])


async def extract_topics_fast(text: str, max_topics: int = 5) -> list[str]:
    """
    Quick topic extraction without full concept analysis.
    Uses simple keyword extraction for speed.
    """
    # Simple keyword-based approach for fast processing
    # Could be enhanced with TF-IDF or other methods
    from collections import Counter
    import re

    # Clean text
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())

    # Common stop words
    stop_words = {
        'that', 'this', 'with', 'have', 'will', 'from', 'they', 'been',
        'were', 'being', 'their', 'which', 'would', 'there', 'could',
        'about', 'other', 'than', 'then', 'these', 'some', 'what',
        'when', 'your', 'just', 'into', 'also', 'more', 'very',
    }

    # Filter and count
    filtered = [w for w in words if w not in stop_words]
    counts = Counter(filtered)

    # Return top topics
    return [word for word, _ in counts.most_common(max_topics)]
