"""DeepEval integration for Emma response evaluation."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Union

from deepeval import evaluate
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    HallucinationMetric,
    ContextualRelevancyMetric,
    BiasMetric,
    ToxicityMetric,
    GEval,
)
from deepeval.test_case import LLMTestCase
from deepeval.test_case.llm_test_case import LLMTestCaseParams
from deepeval.dataset import EvaluationDataset
from deepeval.models.base_model import DeepEvalBaseLLM
from pydantic import BaseModel

from moats_library.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """Evaluation result container."""

    metric_name: str
    score: float
    passed: bool
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "metric": self.metric_name,
            "score": self.score,
            "passed": self.passed,
            "reason": self.reason,
        }


class OpenRouterLLM(DeepEvalBaseLLM):
    """Custom LLM wrapper for OpenRouter to use with DeepEval."""

    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.model_name = model or settings.chat_model
        self.api_key = settings.openrouter_api_key
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.app_url,
            "X-Title": settings.app_name,
        }
        super().__init__(model=self.model_name)

    def load_model(self):
        return self.model_name

    def generate(self, prompt: str, schema: type[BaseModel] | None = None) -> Union[str, BaseModel]:
        """Synchronous generation for DeepEval."""
        import httpx

        messages = [{"role": "user", "content": prompt}]

        # If schema is requested, instruct LLM to output JSON
        if schema:
            schema_json = json.dumps(schema.model_json_schema(), indent=2)
            messages = [
                {"role": "system", "content": f"You must respond with valid JSON that matches this schema:\n{schema_json}\nOnly output the JSON object, nothing else."},
                {"role": "user", "content": prompt},
            ]

        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=self._headers,
            json={
                "model": self.model_name,
                "messages": messages,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]

        if schema:
            return self._parse_schema(content, schema)
        return content

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None) -> Union[str, BaseModel]:
        """Async generation for DeepEval."""
        import httpx

        messages = [{"role": "user", "content": prompt}]

        # If schema is requested, instruct LLM to output JSON
        if schema:
            schema_json = json.dumps(schema.model_json_schema(), indent=2)
            messages = [
                {"role": "system", "content": f"You must respond with valid JSON that matches this schema:\n{schema_json}\nOnly output the JSON object, nothing else."},
                {"role": "user", "content": prompt},
            ]

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=self._headers,
                json={
                    "model": self.model_name,
                    "messages": messages,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

        if schema:
            return self._parse_schema(content, schema)
        return content

    def _parse_schema(self, content: str, schema: type[BaseModel]) -> BaseModel:
        """Parse LLM response into a Pydantic schema."""
        # Strip markdown code fences if present
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # Remove opening ```json or ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        # Try to extract JSON object or array
        text = text.strip()
        if not text.startswith(("{", "[")):
            start = text.find("{")
            if start == -1:
                start = text.find("[")
            if start != -1:
                text = text[start:]

        try:
            data = json.loads(text)
            return schema(**data) if isinstance(data, dict) else schema.model_validate(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse schema response: {e}, content: {content[:200]}")
            raise

    def get_model_name(self) -> str:
        return self.model_name


def get_eval_llm() -> OpenRouterLLM:
    """Get the LLM instance for evaluation."""
    return OpenRouterLLM()


async def _measure_metric(metric, test_case, metric_name: str, invert_score: bool = False) -> EvalResult:
    """Run a single metric and return an EvalResult."""
    try:
        await metric.a_measure(test_case)
        score = (1 - metric.score) if invert_score else metric.score
        return EvalResult(
            metric_name=metric_name,
            score=score,
            passed=metric.is_successful(),
            reason=metric.reason,
        )
    except Exception as e:
        return EvalResult(
            metric_name=metric_name,
            score=0.0,
            passed=False,
            reason=f"Error: {str(e)}",
        )


async def evaluate_response(
    question: str,
    response: str,
    context: list[str] | None = None,
) -> list[EvalResult]:
    """
    Evaluate a single response using DeepEval's evaluate() function.

    Args:
        question: The user's question
        response: Emma's response
        context: Retrieved context chunks (for RAG evaluation)

    Returns:
        List of evaluation results
    """
    llm = get_eval_llm()

    # Create test case
    test_case = LLMTestCase(
        input=question,
        actual_output=response,
        retrieval_context=context,
    )

    # Build metrics list
    metrics = [
        AnswerRelevancyMetric(threshold=0.7, model=llm),
        BiasMetric(threshold=0.7, model=llm),
        ToxicityMetric(threshold=0.7, model=llm),
    ]

    # If we have context, add RAG-specific metrics
    if context:
        metrics.append(FaithfulnessMetric(threshold=0.7, model=llm))
        metrics.append(ContextualRelevancyMetric(threshold=0.7, model=llm))

    # Use deepeval.evaluate() for proper batch evaluation
    try:
        eval_result = evaluate(
            test_cases=[test_case],
            metrics=metrics,
            run_async=True,
            print_results=False,
        )

        # Convert to EvalResult objects
        results = []
        for metric in metrics:
            score = metric.score if metric.score is not None else 0.0
            results.append(EvalResult(
                metric_name=metric.__class__.__name__.replace("Metric", ""),
                score=score,
                passed=metric.is_successful(),
                reason=metric.reason,
            ))
        return results

    except Exception as e:
        logger.error(f"evaluate() failed, falling back to individual metrics: {e}")
        # Fallback to individual measurement
        tasks = [_measure_metric(m, test_case, m.__class__.__name__.replace("Metric", "")) for m in metrics]
        return list(await asyncio.gather(*tasks))


async def evaluate_rag(
    question: str,
    response: str,
    context: list[str],
    expected_output: str | None = None,
) -> list[EvalResult]:
    """
    Comprehensive RAG evaluation.

    Args:
        question: User question
        response: Emma's response
        context: Retrieved chunks
        expected_output: Optional expected answer for comparison

    Returns:
        List of evaluation results
    """
    llm = get_eval_llm()

    # Create test case with both context and retrieval_context
    # HallucinationMetric uses 'context' (ground truth)
    # Faithfulness/ContextualRelevancy use 'retrieval_context' (what RAG retrieved)
    test_case = LLMTestCase(
        input=question,
        actual_output=response,
        context=context,
        retrieval_context=context,
        expected_output=expected_output,
    )

    # Build all metrics
    metrics = []

    # Hallucination check (requires context field)
    if context:
        metrics.append(HallucinationMetric(threshold=0.5, model=llm))

    # G-Eval for overall quality
    metrics.append(GEval(
        name="Response Quality",
        criteria="Evaluate if the response accurately addresses the question using the provided context, is complete, and well-structured.",
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.RETRIEVAL_CONTEXT,
        ],
        model=llm,
    ))

    # Use deepeval.evaluate() for proper batch evaluation
    try:
        eval_result = evaluate(
            test_cases=[test_case],
            metrics=metrics,
            run_async=True,
            print_results=False,
        )

        rag_results = []
        for metric in metrics:
            score = metric.score if metric.score is not None else 0.0
            metric_name = getattr(metric, 'name', metric.__class__.__name__.replace("Metric", ""))
            # Invert hallucination score (lower = better in DeepEval, but we want higher = better)
            if isinstance(metric, HallucinationMetric):
                score = 1 - score
                metric_name = "Hallucination"
            rag_results.append(EvalResult(
                metric_name=metric_name,
                score=score,
                passed=metric.is_successful(),
                reason=metric.reason,
            ))
    except Exception as e:
        logger.error(f"evaluate() failed for RAG, falling back: {e}")
        tasks = []
        for metric in metrics:
            name = getattr(metric, 'name', metric.__class__.__name__.replace("Metric", ""))
            invert = isinstance(metric, HallucinationMetric)
            tasks.append(_measure_metric(metric, test_case, name, invert_score=invert))
        rag_results = list(await asyncio.gather(*tasks))

    # Run standard metrics (includes Bias/Toxicity)
    standard_results = await evaluate_response(question, response, context)
    rag_results.extend(standard_results)

    return rag_results


async def run_redteam(
    system_prompt: str,
    num_attacks: int = 5,
) -> dict[str, Any]:
    """
    Run red team evaluation on Emma.

    Requires the 'deepteam' package: pip install deepteam

    Args:
        system_prompt: Emma's system prompt
        num_attacks: Number of attack attempts per vulnerability

    Returns:
        Red team results with vulnerabilities found
    """
    try:
        from deepteam import red_team
        from deepteam.vulnerabilities import (
            Bias,
            Toxicity,
            PII,
            Misinformation,
        )
        from deepteam.attacks.single_turn import PromptInjection, JailBreaking
    except ImportError:
        return {
            "vulnerabilities_found": 0,
            "vulnerabilities": [],
            "total_attacks": 0,
            "successful_attacks": 0,
            "error": "Red teaming requires the 'deepteam' package. Install with: pip install deepteam",
        }

    llm = get_eval_llm()

    # Create a model callback that simulates Emma's behavior
    async def emma_callback(prompt: str) -> str:
        return await llm.a_generate(
            f"System: {system_prompt}\n\nUser: {prompt}"
        )

    try:
        results = red_team(
            model_callback=emma_callback,
            vulnerabilities=[Bias(), Toxicity(), PII(), Misinformation()],
            attacks=[PromptInjection(), JailBreaking()],
        )

        return {
            "vulnerabilities_found": len(results.vulnerabilities) if hasattr(results, 'vulnerabilities') else 0,
            "vulnerabilities": [
                {
                    "type": str(getattr(v, 'vulnerability_type', 'unknown')),
                    "severity": str(getattr(v, 'severity', 'unknown')),
                    "attack": str(getattr(v, 'input', ''))[:200],
                    "response": str(getattr(v, 'actual_output', ''))[:200],
                }
                for v in (results.vulnerabilities if hasattr(results, 'vulnerabilities') else [])
            ],
            "total_attacks": getattr(results, 'total_attacks', 0),
            "successful_attacks": getattr(results, 'successful_attacks', 0),
        }
    except Exception as e:
        logger.error(f"Red team error: {e}", exc_info=True)
        return {
            "vulnerabilities_found": 0,
            "vulnerabilities": [],
            "total_attacks": 0,
            "successful_attacks": 0,
            "error": f"Red team evaluation failed: {str(e)}",
        }


def format_eval_results(results: list[EvalResult]) -> str:
    """Format evaluation results for display."""
    lines = ["## Evaluation Results\n"]

    passed_count = sum(1 for r in results if r.passed)
    total = len(results)

    lines.append(f"**Overall: {passed_count}/{total} metrics passed**\n")
    lines.append("| Metric | Score | Status |")
    lines.append("|--------|-------|--------|")

    for result in results:
        status = "Pass" if result.passed else "Fail"
        score = f"{result.score:.2f}" if result.score is not None else "N/A"
        lines.append(f"| {result.metric_name} | {score} | {status} |")

    # Add reasons for failures
    failures = [r for r in results if not r.passed and r.reason]
    if failures:
        lines.append("\n### Issues Found\n")
        for r in failures:
            lines.append(f"- **{r.metric_name}**: {r.reason}")

    return "\n".join(lines)
