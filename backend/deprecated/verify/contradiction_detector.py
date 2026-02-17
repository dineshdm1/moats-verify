"""Detect contradiction types between claims and evidence."""

import json
import logging
from dataclasses import dataclass
from enum import Enum

from backend.llm.provider import LLMProvider
from backend.deprecated.verify.claim_extractor import Claim
from backend.deprecated.verify.dual_retrieval import EvidenceChunk

logger = logging.getLogger(__name__)


class ContradictionType(str, Enum):
    NEGATION = "NEGATION"
    TEMPORAL = "TEMPORAL"
    MAGNITUDE = "MAGNITUDE"
    IMPLICATION = "IMPLICATION"
    SUPERSESSION = "SUPERSESSION"
    NONE = "NONE"


@dataclass
class ContradictionAnalysis:
    has_contradiction: bool
    contradiction_type: ContradictionType
    explanation: str
    supporting_evidence: list[str]
    contradicting_evidence: list[str]


CONTRADICTION_PROMPT = """You are a contradiction detector. Analyze whether the evidence supports or contradicts the claim.

Claim: {claim}
Claim Type: {claim_type}

Evidence passages:
{evidence}

Analyze for these contradiction types:
- NEGATION: Direct negation ("profitable" vs "not profitable")
- TEMPORAL: True at one time, false at another ("CEO in 2023" vs "resigned in 2024")
- MAGNITUDE: Numbers/amounts don't match ("grew 15%" vs "grew 5%")
- IMPLICATION: Logical inconsistency ("all shipped" vs "Product X delayed")
- SUPERSESSION: Old info replaced by newer info

Output as JSON:
{{
  "has_contradiction": true/false,
  "contradiction_type": "NEGATION|TEMPORAL|MAGNITUDE|IMPLICATION|SUPERSESSION|NONE",
  "explanation": "Brief explanation of the contradiction or support",
  "supporting_evidence": ["exact quotes that support the claim"],
  "contradicting_evidence": ["exact quotes that contradict the claim"]
}}"""


async def detect_contradictions(
    claim: Claim,
    evidence: list[EvidenceChunk],
    llm: LLMProvider,
) -> ContradictionAnalysis:
    """Analyze evidence for contradictions against a claim."""
    if not evidence:
        return ContradictionAnalysis(
            has_contradiction=False,
            contradiction_type=ContradictionType.NONE,
            explanation="No evidence found to analyze.",
            supporting_evidence=[],
            contradicting_evidence=[],
        )

    evidence_text = "\n\n".join(
        f"[{i+1}] (Source: {e.document_title}, Page {e.page or '?'})\n{e.text}"
        for i, e in enumerate(evidence[:8])  # Limit to top 8 evidence chunks
    )

    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": "You detect contradictions between claims and evidence. Always respond with valid JSON."},
                {"role": "user", "content": CONTRADICTION_PROMPT.format(
                    claim=claim.text,
                    claim_type=claim.claim_type.value,
                    evidence=evidence_text,
                )},
            ],
            temperature=0.0,
            json_mode=True,
        )

        data = json.loads(response)

        try:
            ct = ContradictionType(data.get("contradiction_type", "NONE").upper())
        except ValueError:
            ct = ContradictionType.NONE

        return ContradictionAnalysis(
            has_contradiction=data.get("has_contradiction", False),
            contradiction_type=ct,
            explanation=data.get("explanation", ""),
            supporting_evidence=data.get("supporting_evidence", []),
            contradicting_evidence=data.get("contradicting_evidence", []),
        )

    except Exception as e:
        logger.error(f"Contradiction detection failed: {e}")
        return ContradictionAnalysis(
            has_contradiction=False,
            contradiction_type=ContradictionType.NONE,
            explanation=f"Analysis failed: {e}",
            supporting_evidence=[],
            contradicting_evidence=[],
        )
