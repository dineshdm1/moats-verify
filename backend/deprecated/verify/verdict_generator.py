"""Generate verdicts for claims based on evidence and contradiction analysis."""

import json
import logging
from dataclasses import dataclass
from enum import Enum

from backend.llm.provider import LLMProvider
from backend.deprecated.verify.claim_extractor import Claim
from backend.deprecated.verify.dual_retrieval import EvidenceChunk
from backend.deprecated.verify.contradiction_detector import ContradictionAnalysis, ContradictionType

logger = logging.getLogger(__name__)


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    CONFLICTING = "CONFLICTING"
    NO_EVIDENCE = "NO_EVIDENCE"


@dataclass
class ClaimVerdict:
    claim: str
    claim_type: str
    verdict: Verdict
    confidence: float
    reasoning: str
    evidence_used: str
    contradiction_type: ContradictionType | None
    contradiction_explanation: str | None
    sources: list[dict]  # [{document_title, page, paragraph}]
    temporal_context: dict | None  # {claim_timeframe, evidence_timeframe, temporal_gap}


VERDICT_PROMPT = """You are a verification engine. Given a claim and evidence passages, determine the verdict.

Claim: {claim}
Claim Type: {claim_type}

Evidence passages:
{evidence}

Contradiction Analysis:
{contradiction_analysis}

Rules:
- SUPPORTED: Evidence directly confirms the claim
- PARTIALLY_SUPPORTED: Evidence confirms part of the claim but not all
- CONTRADICTED: Evidence directly opposes the claim
- CONFLICTING: Some evidence supports, other evidence contradicts
- NO_EVIDENCE: Evidence does not address the claim

For CONTRADICTED verdicts, identify the contradiction type:
- NEGATION: Direct negation of the claim
- TEMPORAL: True at one time, false at another
- MAGNITUDE: Numbers/amounts don't match
- IMPLICATION: Logical inconsistency
- SUPERSESSION: Newer information replaces older

Output as JSON:
{{
  "verdict": "SUPPORTED|PARTIALLY_SUPPORTED|CONTRADICTED|CONFLICTING|NO_EVIDENCE",
  "reasoning": "Brief explanation",
  "evidence_used": "The specific passage that led to this verdict",
  "confidence": 0.0-1.0
}}

Important:
- Do not infer beyond what evidence states
- If ambiguous, lean toward NO_EVIDENCE
- Quote exact evidence supporting your verdict"""


async def generate_verdict(
    claim: Claim,
    evidence: list[EvidenceChunk],
    contradiction: ContradictionAnalysis,
    llm: LLMProvider,
) -> ClaimVerdict:
    """Generate a verdict for a single claim."""
    if not evidence:
        return ClaimVerdict(
            claim=claim.text,
            claim_type=claim.claim_type.value,
            verdict=Verdict.NO_EVIDENCE,
            confidence=0.9,
            reasoning="No relevant evidence found in the document library.",
            evidence_used="",
            contradiction_type=None,
            contradiction_explanation=None,
            sources=[],
            temporal_context=None,
        )

    evidence_text = "\n\n".join(
        f"[{i+1}] (Source: {e.document_title}, Page {e.page or '?'})\n{e.text}"
        for i, e in enumerate(evidence[:8])
    )

    contradiction_text = (
        f"Has contradiction: {contradiction.has_contradiction}\n"
        f"Type: {contradiction.contradiction_type.value}\n"
        f"Explanation: {contradiction.explanation}\n"
        f"Supporting: {contradiction.supporting_evidence}\n"
        f"Contradicting: {contradiction.contradicting_evidence}"
    )

    try:
        response = await llm.chat(
            messages=[
                {"role": "system", "content": "You are a verification engine that judges claims against evidence. Always respond with valid JSON."},
                {"role": "user", "content": VERDICT_PROMPT.format(
                    claim=claim.text,
                    claim_type=claim.claim_type.value,
                    evidence=evidence_text,
                    contradiction_analysis=contradiction_text,
                )},
            ],
            temperature=0.0,
            json_mode=True,
        )

        data = json.loads(response)

        try:
            verdict = Verdict(data.get("verdict", "NO_EVIDENCE").upper())
        except ValueError:
            verdict = Verdict.NO_EVIDENCE

        # Reconcile: if contradiction detector found a contradiction but LLM
        # returned NO_EVIDENCE or SUPPORTED, override based on contradiction
        if contradiction.has_contradiction:
            if verdict == Verdict.NO_EVIDENCE:
                # Contradiction found but LLM said no evidence — trust the contradiction detector
                verdict = Verdict.CONTRADICTED
            elif verdict == Verdict.SUPPORTED and contradiction.contradiction_type in (
                ContradictionType.NEGATION, ContradictionType.MAGNITUDE,
            ):
                # Hard contradiction types override SUPPORTED
                verdict = Verdict.CONTRADICTED
            elif verdict == Verdict.SUPPORTED and contradiction.contradiction_type in (
                ContradictionType.IMPLICATION, ContradictionType.TEMPORAL, ContradictionType.SUPERSESSION,
            ):
                # Softer contradiction types → CONFLICTING
                verdict = Verdict.CONFLICTING

        # Build sources list
        sources = []
        seen = set()
        for e in evidence[:5]:
            key = (e.document_title, e.page)
            if key not in seen:
                seen.add(key)
                sources.append({
                    "document_title": e.document_title,
                    "page": e.page,
                    "paragraph": e.paragraph,
                    "document_id": e.document_id,
                })

        # Build temporal context
        temporal_context = None
        if claim.temporal_context:
            temporal_context = {
                "claim_timeframe": claim.temporal_context,
                "evidence_timeframe": None,
                "temporal_gap": None,
                "temporal_status": None,
            }

        return ClaimVerdict(
            claim=claim.text,
            claim_type=claim.claim_type.value,
            verdict=verdict,
            confidence=min(max(data.get("confidence", 0.5), 0.0), 1.0),
            reasoning=data.get("reasoning", ""),
            evidence_used=data.get("evidence_used", ""),
            contradiction_type=contradiction.contradiction_type if contradiction.has_contradiction else None,
            contradiction_explanation=contradiction.explanation if contradiction.has_contradiction else None,
            sources=sources,
            temporal_context=temporal_context,
        )

    except Exception as e:
        logger.error(f"Verdict generation failed: {e}")
        return ClaimVerdict(
            claim=claim.text,
            claim_type=claim.claim_type.value,
            verdict=Verdict.NO_EVIDENCE,
            confidence=0.0,
            reasoning=f"Verdict generation failed: {e}",
            evidence_used="",
            contradiction_type=None,
            contradiction_explanation=None,
            sources=[],
            temporal_context=None,
        )
