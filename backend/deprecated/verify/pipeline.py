"""Full verification pipeline — orchestrates the entire flow."""

import logging
from dataclasses import dataclass, asdict
from typing import Callable

from backend.deprecated.verify.claim_extractor import extract_claims, Claim
from backend.deprecated.verify.dual_retrieval import retrieve_evidence
from backend.deprecated.verify.reranker import rerank_evidence
from backend.deprecated.verify.contradiction_detector import detect_contradictions
from backend.deprecated.verify.verdict_generator import generate_verdict, ClaimVerdict, Verdict
from backend.storage.chromadb import VectorStore
from backend.storage.neo4j import GraphStore
from backend.storage.sqlite import MetadataDB
from backend.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class VerificationOutput:
    verification_id: str
    trust_score: float
    total_claims: int
    supported: int
    partially_supported: int
    contradicted: int
    conflicting: int
    no_evidence: int
    verdicts: list[dict]


async def run_verification(
    text: str,
    library_id: str,
    db: MetadataDB,
    vector_store: VectorStore,
    graph_store: GraphStore | None,
    llm: LLMProvider,
    progress_callback: Callable | None = None,
) -> VerificationOutput:
    """
    Run the full verification pipeline:
    1. Extract claims
    2. For each claim: retrieve evidence → rerank → detect contradictions → generate verdict
    3. Compute trust score
    4. Save results
    """

    # Step 1: Extract claims
    if progress_callback:
        await progress_callback("extracting_claims", 0, "Extracting claims...")

    claims = await extract_claims(text, llm)

    if progress_callback:
        await progress_callback("extracting_claims", 100, f"Found {len(claims)} claims")

    if not claims:
        ver_id = db.save_verification(library_id, text, 0.0, [])
        return VerificationOutput(
            verification_id=ver_id, trust_score=0.0, total_claims=0,
            supported=0, partially_supported=0, contradicted=0,
            conflicting=0, no_evidence=0, verdicts=[],
        )

    # Step 2-5: Process each claim
    verdicts: list[ClaimVerdict] = []

    for i, claim in enumerate(claims):
        step_name = f"Verifying claim {i + 1}/{len(claims)}"

        # Retrieve evidence
        if progress_callback:
            await progress_callback("retrieving", int((i / len(claims)) * 100), f"{step_name}: retrieving evidence...")

        evidence = await retrieve_evidence(
            claim=claim,
            library_id=library_id,
            vector_store=vector_store,
            graph_store=graph_store,
            llm=llm,
            top_k=15,
        )

        # Rerank
        evidence = rerank_evidence(claim.text, evidence, top_k=5)

        # Detect contradictions
        if progress_callback:
            await progress_callback("analyzing", int((i / len(claims)) * 100), f"{step_name}: analyzing contradictions...")

        contradiction = await detect_contradictions(claim, evidence, llm)

        # Generate verdict
        if progress_callback:
            await progress_callback("judging", int((i / len(claims)) * 100), f"{step_name}: generating verdict...")

        verdict = await generate_verdict(claim, evidence, contradiction, llm)
        verdicts.append(verdict)

    # Step 6: Compute trust score
    if progress_callback:
        await progress_callback("scoring", 90, "Computing trust score...")

    trust_score = _compute_trust_score(verdicts)

    # Count verdicts
    counts = {v: 0 for v in Verdict}
    for v in verdicts:
        counts[v.verdict] += 1

    # Step 7: Save results
    verdict_dicts = [_verdict_to_dict(v) for v in verdicts]
    ver_id = db.save_verification(library_id, text, trust_score, verdict_dicts)

    if progress_callback:
        await progress_callback("complete", 100, "Verification complete")

    return VerificationOutput(
        verification_id=ver_id,
        trust_score=trust_score,
        total_claims=len(claims),
        supported=counts[Verdict.SUPPORTED],
        partially_supported=counts[Verdict.PARTIALLY_SUPPORTED],
        contradicted=counts[Verdict.CONTRADICTED],
        conflicting=counts[Verdict.CONFLICTING],
        no_evidence=counts[Verdict.NO_EVIDENCE],
        verdicts=verdict_dicts,
    )


def _compute_trust_score(verdicts: list[ClaimVerdict]) -> float:
    """Compute aggregate trust score from individual verdicts."""
    if not verdicts:
        return 0.0

    # If ALL claims are NO_EVIDENCE, score is 0 (we can't verify anything)
    if all(v.verdict == Verdict.NO_EVIDENCE for v in verdicts):
        return 0.0

    weights = {
        Verdict.SUPPORTED: 1.0,
        Verdict.PARTIALLY_SUPPORTED: 0.6,
        Verdict.CONTRADICTED: 0.0,
        Verdict.CONFLICTING: 0.3,
        Verdict.NO_EVIDENCE: 0.0,  # No evidence = no trust contribution
    }

    # Only count claims that have evidence for the denominator
    scored = [v for v in verdicts if v.verdict != Verdict.NO_EVIDENCE]
    if not scored:
        return 0.0

    total = sum(weights[v.verdict] * v.confidence for v in scored)
    max_possible = sum(v.confidence for v in scored)

    if max_possible == 0:
        return 0.0

    return round(total / max_possible, 2)


def _verdict_to_dict(v: ClaimVerdict) -> dict:
    return {
        "claim": v.claim,
        "claim_type": v.claim_type,
        "verdict": v.verdict.value,
        "confidence": v.confidence,
        "reasoning": v.reasoning,
        "evidence_used": v.evidence_used,
        "contradiction_type": v.contradiction_type.value if v.contradiction_type else None,
        "contradiction_explanation": v.contradiction_explanation,
        "sources": v.sources,
        "temporal_context": v.temporal_context,
    }
