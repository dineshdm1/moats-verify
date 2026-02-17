"""Extract entities from text chunks using LLM."""

import json
import logging
from dataclasses import dataclass

from backend.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

ENTITY_EXTRACTION_PROMPT = """You are an entity extractor. Extract all named entities from the text.

For each entity, provide:
- name: The entity name (normalized, consistent casing)
- type: One of: person, organization, product, location, date, metric, policy, event, concept
- description: Brief description (1 sentence)

Also extract relationships between entities:
- from: Source entity name
- to: Target entity name
- type: Relationship type (e.g., CEO_OF, LOCATED_IN, PRODUCES, ACQUIRED, REPORTED, etc.)

Text:
{text}

Output as JSON:
{
  "entities": [
    {"name": "...", "type": "...", "description": "..."}
  ],
  "relationships": [
    {"from": "...", "to": "...", "type": "..."}
  ]
}"""


@dataclass
class ExtractedEntity:
    name: str
    entity_type: str
    description: str


@dataclass
class ExtractedRelationship:
    from_entity: str
    to_entity: str
    rel_type: str


@dataclass
class ExtractionResult:
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]


async def extract_entities(text: str, llm: LLMProvider) -> ExtractionResult:
    """Extract entities and relationships from text using LLM."""
    # Truncate to avoid context limits
    text = text[:6000]

    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": "You extract entities and relationships from text. Always respond with valid JSON."},
                {"role": "user", "content": ENTITY_EXTRACTION_PROMPT.format(text=text)},
            ],
            temperature=0.0,
            json_mode=True,
        )

        data = json.loads(response)

        entities = [
            ExtractedEntity(
                name=e.get("name", ""),
                entity_type=e.get("type", "concept"),
                description=e.get("description", ""),
            )
            for e in data.get("entities", [])
            if e.get("name")
        ]

        relationships = [
            ExtractedRelationship(
                from_entity=r.get("from", ""),
                to_entity=r.get("to", ""),
                rel_type=r.get("type", "RELATES_TO"),
            )
            for r in data.get("relationships", [])
            if r.get("from") and r.get("to")
        ]

        return ExtractionResult(entities=entities, relationships=relationships)

    except Exception as e:
        logger.warning(f"Entity extraction failed: {e}")
        return ExtractionResult(entities=[], relationships=[])


async def extract_entities_batch(chunks: list[dict], llm: LLMProvider,
                                  batch_size: int = 5) -> list[ExtractionResult]:
    """Extract entities from multiple chunks."""
    results = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        # Combine batch texts for efficiency
        combined = "\n\n---\n\n".join(c.get("text", c) if isinstance(c, dict) else c for c in batch)
        result = await extract_entities(combined, llm)
        results.append(result)
    return results
