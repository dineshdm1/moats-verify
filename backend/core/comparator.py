"""Compare claim structure against evidence structure."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ComparisonResult(Enum):
    MATCH = "match"
    CONTRADICTION = "contradiction"
    PARTIAL = "partial"
    NO_COMPARISON = "no_comparison"


@dataclass
class Comparison:
    result: ComparisonResult
    contradiction_type: Optional[str]
    confidence: float
    explanation: str


class Comparator:
    """Compare claim and evidence structures."""

    def __init__(self, numeric_tolerance: float = 0.05):
        self.numeric_tolerance = numeric_tolerance

    def compare(self, claim: "ClaimStructure", evidence: "ClaimStructure") -> Comparison:
        """Compare claim against evidence."""

        if claim.numeric_values and evidence.numeric_values:
            result = self._compare_numeric(claim, evidence)
            if result.result != ComparisonResult.NO_COMPARISON:
                return result

        if claim.temporal_values and evidence.temporal_values:
            result = self._compare_temporal(claim, evidence)
            if result.result != ComparisonResult.NO_COMPARISON:
                return result

        if claim.polarity != "uncertain" and evidence.polarity != "uncertain":
            result = self._compare_polarity(claim, evidence)
            if result.result != ComparisonResult.NO_COMPARISON:
                return result

        return Comparison(
            result=ComparisonResult.NO_COMPARISON,
            contradiction_type=None,
            confidence=0.0,
            explanation="Cannot compare structurally, requires reasoning",
        )

    def _compare_numeric(self, claim: "ClaimStructure", evidence: "ClaimStructure") -> Comparison:
        claim_num = claim.numeric_values[0]
        evidence_num = evidence.numeric_values[0]

        if claim_num.unit != evidence_num.unit:
            return Comparison(
                result=ComparisonResult.NO_COMPARISON,
                contradiction_type=None,
                confidence=0.0,
                explanation=f"Different units: {claim_num.unit} vs {evidence_num.unit}",
            )

        if abs(evidence_num.value) < 1e-10:
            if abs(claim_num.value) < 1e-10:
                return Comparison(
                    result=ComparisonResult.MATCH,
                    contradiction_type=None,
                    confidence=0.95,
                    explanation="Both values are zero",
                )
            return Comparison(
                result=ComparisonResult.CONTRADICTION,
                contradiction_type="magnitude",
                confidence=0.95,
                explanation=f"Claim: {claim_num.raw}, Evidence: ~0",
            )

        diff = abs(claim_num.value - evidence_num.value) / abs(evidence_num.value)

        if diff <= self.numeric_tolerance:
            return Comparison(
                result=ComparisonResult.MATCH,
                contradiction_type=None,
                confidence=min(claim_num.confidence, evidence_num.confidence),
                explanation=(
                    f"Values match: {claim_num.raw} approx {evidence_num.raw} "
                    f"(within {self.numeric_tolerance * 100:.0f}% tolerance)"
                ),
            )

        return Comparison(
            result=ComparisonResult.CONTRADICTION,
            contradiction_type="magnitude",
            confidence=min(claim_num.confidence, evidence_num.confidence) * 0.95,
            explanation=(
                f"Values differ: claim says {claim_num.raw}, evidence says "
                f"{evidence_num.raw} ({diff * 100:.1f}% difference)"
            ),
        )

    def _compare_temporal(self, claim: "ClaimStructure", evidence: "ClaimStructure") -> Comparison:
        claim_temp = claim.temporal_values[0]
        evidence_temp = evidence.temporal_values[0]

        if claim_temp.start <= evidence_temp.end and evidence_temp.start <= claim_temp.end:
            start_diff = abs((claim_temp.start - evidence_temp.start).days)
            end_diff = abs((claim_temp.end - evidence_temp.end).days)

            if start_diff <= 7 and end_diff <= 7:
                return Comparison(
                    result=ComparisonResult.MATCH,
                    contradiction_type=None,
                    confidence=min(claim_temp.confidence, evidence_temp.confidence),
                    explanation=f"Time periods match: {claim_temp.raw} approx {evidence_temp.raw}",
                )

            return Comparison(
                result=ComparisonResult.PARTIAL,
                contradiction_type="temporal",
                confidence=0.7,
                explanation=(
                    f"Time periods overlap but differ: {claim_temp.raw} vs "
                    f"{evidence_temp.raw}"
                ),
            )

        return Comparison(
            result=ComparisonResult.CONTRADICTION,
            contradiction_type="temporal",
            confidence=min(claim_temp.confidence, evidence_temp.confidence) * 0.9,
            explanation=(
                f"Time periods do not match: claim says {claim_temp.raw}, "
                f"evidence says {evidence_temp.raw}"
            ),
        )

    def _compare_polarity(self, claim: "ClaimStructure", evidence: "ClaimStructure") -> Comparison:
        if claim.polarity == evidence.polarity:
            return Comparison(
                result=ComparisonResult.MATCH,
                contradiction_type=None,
                confidence=0.75,
                explanation="Statement polarity matches",
            )

        return Comparison(
            result=ComparisonResult.CONTRADICTION,
            contradiction_type="negation",
            confidence=0.85,
            explanation=(
                f"Polarity mismatch: claim is {claim.polarity}, "
                f"evidence is {evidence.polarity}"
            ),
        )
