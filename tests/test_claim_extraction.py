"""Tests for claim segmentation in the core pipeline."""

from backend.core.segmenter import ClaimSegmenter


def test_segmenter_splits_and_filters_questions():
    segmenter = ClaimSegmenter()
    text = "Revenue grew 15% in Q3 2024. What is the forecast? Margin improved to 20%."

    claims = segmenter.segment(text)

    assert claims == [
        "Revenue grew 15% in Q3 2024.",
        "Margin improved to 20%.",
    ]


def test_segmenter_filters_commands():
    segmenter = ClaimSegmenter()
    text = "Summarize this report. Revenue reached $5M in Q3 2024."

    claims = segmenter.segment(text)

    assert claims == ["Revenue reached $5M in Q3 2024."]


def test_segmenter_empty_input():
    segmenter = ClaimSegmenter()

    assert segmenter.segment("") == []
    assert segmenter.segment("   ") == []
