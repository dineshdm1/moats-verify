"""Generate final verdict from comparison results.
Falls back to LLM when needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .comparator import ComparisonResult


class Verdict(Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    PARTIAL = "partial"
    NO_EVIDENCE = "no_evidence"


@dataclass
class ClaimVerdict:
    claim_text: str
    verdict: Verdict
    confidence: float
    evidence_text: str
    evidence_source: str
    evidence_page: Optional[int]
    reason: str
    used_llm: bool
    contradiction_type: Optional[str] = None


class VerdictGenerator:
    """Generate verdicts from comparison results."""

    def __init__(self, llm_provider):
        self.llm = llm_provider

    async def generate(
        self,
        claim: "ClaimStructure",
        evidence_passages: list[dict],
        comparison: "Comparison",
    ) -> ClaimVerdict:
        """Generate verdict for a claim."""

        if not evidence_passages:
            return ClaimVerdict(
                claim_text=claim.text,
                verdict=Verdict.NO_EVIDENCE,
                confidence=0.95,
                evidence_text="",
                evidence_source="",
                evidence_page=None,
                reason="No relevant passages found in your documents.",
                used_llm=False,
                contradiction_type=None,
            )

        best_evidence = evidence_passages[0]

        if comparison.result == ComparisonResult.MATCH:
            return ClaimVerdict(
                claim_text=claim.text,
                verdict=Verdict.SUPPORTED,
                confidence=comparison.confidence,
                evidence_text=best_evidence["text"],
                evidence_source=best_evidence["source"],
                evidence_page=best_evidence.get("page"),
                reason=comparison.explanation,
                used_llm=False,
                contradiction_type=None,
            )

        if comparison.result == ComparisonResult.CONTRADICTION:
            return ClaimVerdict(
                claim_text=claim.text,
                verdict=Verdict.CONTRADICTED,
                confidence=comparison.confidence,
                evidence_text=best_evidence["text"],
                evidence_source=best_evidence["source"],
                evidence_page=best_evidence.get("page"),
                reason=comparison.explanation,
                used_llm=False,
                contradiction_type=comparison.contradiction_type,
            )

        if comparison.result == ComparisonResult.PARTIAL:
            return ClaimVerdict(
                claim_text=claim.text,
                verdict=Verdict.PARTIAL,
                confidence=comparison.confidence,
                evidence_text=best_evidence["text"],
                evidence_source=best_evidence["source"],
                evidence_page=best_evidence.get("page"),
                reason=comparison.explanation,
                used_llm=False,
                contradiction_type=comparison.contradiction_type,
            )

        return await self._llm_verdict(claim, evidence_passages)

    async def _llm_verdict(self, claim: "ClaimStructure", evidence_passages: list[dict]) -> ClaimVerdict:
        """Use LLM when structured comparison isn't possible."""

        evidence_text = "\n\n".join(
            [f"[{p['source']}, page {p.get('page', '?')}]: {p['text']}" for p in evidence_passages[:3]]
        )

        prompt = f"""You are verifying a claim against source documents.

CLAIM: {claim.text}

EVIDENCE FROM DOCUMENTS:
{evidence_text}

Based on the evidence, determine:
1. Does the evidence SUPPORT, CONTRADICT, or PARTIALLY SUPPORT the claim?
2. If there's no relevant evidence, say NO_EVIDENCE.

Respond in this exact format:
VERDICT: [SUPPORTED/CONTRADICTED/PARTIAL/NO_EVIDENCE]
CONFIDENCE: [0.0-1.0]
REASON: [One sentence explaining why]
"""

        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": "You verify claims against evidence. Follow output format exactly."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=300,
        )

        verdict = Verdict.NO_EVIDENCE
        confidence = 0.5
        reason = "Could not determine from evidence."

        for line in response.strip().split("\n"):
            if line.startswith("VERDICT:"):
                value = line.replace("VERDICT:", "").strip().upper()
                if value == "SUPPORTED":
                    verdict = Verdict.SUPPORTED
                elif value == "CONTRADICTED":
                    verdict = Verdict.CONTRADICTED
                elif value == "PARTIAL":
                    verdict = Verdict.PARTIAL
                elif value == "NO_EVIDENCE":
                    verdict = Verdict.NO_EVIDENCE
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.replace("CONFIDENCE:", "").strip())
                except Exception:
                    confidence = 0.5
            elif line.startswith("REASON:"):
                reason = line.replace("REASON:", "").strip()

        best_evidence = evidence_passages[0] if evidence_passages else {}
        return ClaimVerdict(
            claim_text=claim.text,
            verdict=verdict,
            confidence=min(max(confidence, 0.0), 1.0),
            evidence_text=best_evidence.get("text", ""),
            evidence_source=best_evidence.get("source", ""),
            evidence_page=best_evidence.get("page"),
            reason=reason,
            used_llm=True,
            contradiction_type=None,
        )
