"""Tests for core comparator logic."""

from datetime import datetime

from backend.core.comparator import Comparator, ComparisonResult
from backend.core.extractor import ClaimStructure, NumericValue, TemporalValue


def _claim_structure(
    text: str,
    *,
    num: NumericValue | None = None,
    temp: TemporalValue | None = None,
    polarity: str = "positive",
):
    return ClaimStructure(
        text=text,
        numeric_values=[num] if num else [],
        temporal_values=[temp] if temp else [],
        subject="Revenue",
        polarity=polarity,
        negation_words=[],
        extraction_confidence=0.9,
    )


def test_numeric_match():
    comparator = Comparator(numeric_tolerance=0.05)
    claim = _claim_structure(
        "Revenue was $5M",
        num=NumericValue(raw="$5M", value=5_000_000, unit="USD", confidence=0.95),
    )
    evidence = _claim_structure(
        "Revenue reached $5.1M",
        num=NumericValue(raw="$5.1M", value=5_100_000, unit="USD", confidence=0.95),
    )

    result = comparator.compare(claim, evidence)

    assert result.result == ComparisonResult.MATCH


def test_numeric_contradiction():
    comparator = Comparator(numeric_tolerance=0.05)
    claim = _claim_structure(
        "Revenue was $5M",
        num=NumericValue(raw="$5M", value=5_000_000, unit="USD", confidence=0.95),
    )
    evidence = _claim_structure(
        "Revenue was $1.08T",
        num=NumericValue(raw="$1.08T", value=1_080_000_000_000, unit="USD", confidence=0.95),
    )

    result = comparator.compare(claim, evidence)

    assert result.result == ComparisonResult.CONTRADICTION
    assert result.contradiction_type == "magnitude"


def test_temporal_partial_overlap():
    comparator = Comparator()
    claim = _claim_structure(
        "Q3 2024",
        temp=TemporalValue(
            raw="Q3 2024",
            start=datetime(2024, 7, 1),
            end=datetime(2024, 9, 30),
            confidence=0.95,
        ),
    )
    evidence = _claim_structure(
        "2024",
        temp=TemporalValue(
            raw="2024",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 12, 31),
            confidence=0.85,
        ),
    )

    result = comparator.compare(claim, evidence)

    assert result.result == ComparisonResult.PARTIAL
    assert result.contradiction_type == "temporal"


def test_polarity_contradiction():
    comparator = Comparator()
    claim = _claim_structure("Company is profitable", polarity="positive")
    evidence = _claim_structure("Company is not profitable", polarity="negative")

    result = comparator.compare(claim, evidence)

    assert result.result == ComparisonResult.CONTRADICTION
    assert result.contradiction_type == "negation"
