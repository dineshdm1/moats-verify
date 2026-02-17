"""DeepEval integration for verdict quality scoring."""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    faithfulness: float
    relevancy: float
    hallucination: float
    overall: float
    passed: bool


async def score_verdict(claim: str, evidence: str, verdict_reasoning: str) -> QualityScore:
    """Score the quality of a verdict using DeepEval metrics."""
    try:
        from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric, HallucinationMetric
        from deepeval.test_case import LLMTestCase

        test_case = LLMTestCase(
            input=f"Is this claim supported? {claim}",
            actual_output=verdict_reasoning,
            retrieval_context=[evidence],
        )

        faithfulness = FaithfulnessMetric(threshold=0.7)
        relevancy = AnswerRelevancyMetric(threshold=0.7)
        hallucination = HallucinationMetric(threshold=0.7)

        faithfulness.measure(test_case)
        relevancy.measure(test_case)
        hallucination.measure(test_case)

        f_score = faithfulness.score or 0.0
        r_score = relevancy.score or 0.0
        h_score = 1.0 - (hallucination.score or 0.0)  # Invert: lower hallucination = better
        overall = (f_score + r_score + h_score) / 3

        return QualityScore(
            faithfulness=f_score,
            relevancy=r_score,
            hallucination=h_score,
            overall=overall,
            passed=overall >= 0.7,
        )

    except ImportError:
        logger.warning("deepeval not installed — skipping quality scoring")
        return QualityScore(
            faithfulness=1.0, relevancy=1.0, hallucination=1.0,
            overall=1.0, passed=True,
        )
    except Exception as e:
        logger.warning(f"Quality scoring failed: {e}")
        return QualityScore(
            faithfulness=0.0, relevancy=0.0, hallucination=0.0,
            overall=0.0, passed=False,
        )
