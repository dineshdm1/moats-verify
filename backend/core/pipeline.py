"""Main verification pipeline.
Orchestrates: segmentation -> extraction -> retrieval -> comparison -> verdict
"""

from __future__ import annotations

from dataclasses import dataclass

from .comparator import Comparator
from .extractor import StructureExtractor
from .retrieval import EvidenceRetriever
from .segmenter import ClaimSegmenter
from .verdict import ClaimVerdict, Verdict, VerdictGenerator


@dataclass
class VerificationResult:
    trust_score: float
    claims: list[ClaimVerdict]
    total_claims: int
    supported_count: int
    partial_count: int
    contradicted_count: int
    no_evidence_count: int


class VerificationPipeline:
    """Main verification pipeline."""

    def __init__(self, llm_provider, vector_store, numeric_tolerance: float = 0.05):
        self.segmenter = ClaimSegmenter()
        self.extractor = StructureExtractor()
        self.retriever = EvidenceRetriever(vector_store, llm_provider)
        self.comparator = Comparator(numeric_tolerance)
        self.verdict_gen = VerdictGenerator(llm_provider)

    async def verify(self, text: str, library_id: str) -> VerificationResult:
        """Verify all claims in text against documents in library."""

        claim_texts = self.segmenter.segment(text)
        verdicts: list[ClaimVerdict] = []

        for claim_text in claim_texts:
            claim_structure = self.extractor.extract(claim_text)

            evidence_passages = await self.retriever.retrieve(
                query=claim_text,
                library_id=library_id,
                top_k=5,
            )

            if not evidence_passages:
                verdicts.append(
                    ClaimVerdict(
                        claim_text=claim_text,
                        verdict=Verdict.NO_EVIDENCE,
                        confidence=0.95,
                        evidence_text="",
                        evidence_source="",
                        evidence_page=None,
                        reason="No relevant passages found in your documents.",
                        used_llm=False,
                        contradiction_type=None,
                    )
                )
                continue

            evidence_structure = self.extractor.extract(evidence_passages[0]["text"])
            comparison = self.comparator.compare(claim_structure, evidence_structure)

            verdict = await self.verdict_gen.generate(
                claim=claim_structure,
                evidence_passages=evidence_passages,
                comparison=comparison,
            )
            verdicts.append(verdict)

        trust_score = self._calculate_trust_score(verdicts)

        return VerificationResult(
            trust_score=trust_score,
            claims=verdicts,
            total_claims=len(verdicts),
            supported_count=sum(1 for v in verdicts if v.verdict == Verdict.SUPPORTED),
            partial_count=sum(1 for v in verdicts if v.verdict == Verdict.PARTIAL),
            contradicted_count=sum(1 for v in verdicts if v.verdict == Verdict.CONTRADICTED),
            no_evidence_count=sum(1 for v in verdicts if v.verdict == Verdict.NO_EVIDENCE),
        )

    def _calculate_trust_score(self, verdicts: list[ClaimVerdict]) -> float:
        """Calculate weighted trust score."""

        weights = {
            Verdict.SUPPORTED: 1.0,
            Verdict.PARTIAL: 0.6,
            Verdict.CONTRADICTED: 0.0,
            Verdict.NO_EVIDENCE: None,
        }

        weighted_sum = 0.0
        total_weight = 0.0

        for verdict in verdicts:
            weight = weights.get(verdict.verdict)
            if weight is not None:
                weighted_sum += weight * verdict.confidence
                total_weight += verdict.confidence

        if total_weight == 0:
            return 0.0

        return round(weighted_sum / total_weight, 2)
