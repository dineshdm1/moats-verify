"""Extract and classify atomic claims from input text."""

import json
import logging
from dataclasses import dataclass
from enum import Enum

from backend.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class ClaimType(str, Enum):
    FACTUAL = "FACTUAL"
    QUANTITATIVE = "QUANTITATIVE"
    COMPARATIVE = "COMPARATIVE"
    TEMPORAL = "TEMPORAL"
    CAUSAL = "CAUSAL"


@dataclass
class Claim:
    text: str
    claim_type: ClaimType
    original_span: str
    entities: list[str] | None = None
    temporal_context: str | None = None


CLAIM_EXTRACTION_PROMPT = """You are a claim extractor. Extract every factual claim from the text.

Rules:
- Extract only factual claims (not opinions, questions, commands)
- Each claim must be atomic (one fact per claim)
- Preserve original meaning exactly
- Do not infer or add information

For each claim, classify its type:
- FACTUAL: Simple statement of fact
- QUANTITATIVE: Contains numbers, percentages, amounts
- COMPARATIVE: Compares two or more things
- TEMPORAL: Time-bound statement
- CAUSAL: Claims cause-effect relationship

Also extract:
- entities: Key entities mentioned in the claim
- temporal_context: Any time reference (e.g., "Q3 2024", "as of March 2025")

Input text:
{input_text}

Output as JSON:
{{
  "claims": [
    {{
      "claim": "...",
      "type": "FACTUAL|QUANTITATIVE|COMPARATIVE|TEMPORAL|CAUSAL",
      "original_span": "...",
      "entities": ["..."],
      "temporal_context": "..." or null
    }}
  ]
}}"""


async def extract_claims(text: str, llm: LLMProvider) -> list[Claim]:
    """Extract atomic factual claims from input text."""
    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": "You extract factual claims from text. Always respond with valid JSON."},
                {"role": "user", "content": CLAIM_EXTRACTION_PROMPT.format(input_text=text)},
            ],
            temperature=0.0,
            json_mode=True,
        )

        data = json.loads(response)
        claims = []

        for c in data.get("claims", []):
            claim_type_str = c.get("type", "FACTUAL").upper()
            try:
                claim_type = ClaimType(claim_type_str)
            except ValueError:
                claim_type = ClaimType.FACTUAL

            claims.append(Claim(
                text=c.get("claim", ""),
                claim_type=claim_type,
                original_span=c.get("original_span", c.get("claim", "")),
                entities=c.get("entities"),
                temporal_context=c.get("temporal_context"),
            ))

        return claims

    except Exception as e:
        logger.error(f"Claim extraction failed: {e}")
        # Fallback: treat entire text as a single claim
        return [Claim(
            text=text.strip(),
            claim_type=ClaimType.FACTUAL,
            original_span=text.strip(),
        )]
