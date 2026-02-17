"""Verification endpoint."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from backend.api.schemas import VerifyRequest, VerifyResponse, VerificationHistoryItem
from backend.core.pipeline import VerificationPipeline
from backend.core.verdict import Verdict
from backend.main import get_db, get_vector_store, get_llm

router = APIRouter(prefix="/api/verify", tags=["verify"])


@router.post("", response_model=VerifyResponse)
async def verify_text(body: VerifyRequest):
    db = get_db()
    vs = get_vector_store()
    llm = get_llm()

    # Determine library
    library_id = body.library_id
    if not library_id:
        active = db.get_active_library()
        if not active:
            raise HTTPException(status_code=400, detail="No active library. Create a library first.")
        library_id = active.id

    lib = db.get_library(library_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Library not found")

    if lib.chunk_count == 0:
        raise HTTPException(status_code=400, detail="Library has no documents. Add sources first.")

    pipeline = VerificationPipeline(llm_provider=llm, vector_store=vs)
    result = await pipeline.verify(text=body.text, library_id=library_id)

    verdicts = [_to_api_verdict(claim) for claim in result.claims]
    verification_id = db.save_verification(
        library_id=library_id,
        input_text=body.text,
        trust_score=result.trust_score,
        claims=verdicts,
    )

    return {
        "verification_id": verification_id,
        "trust_score": result.trust_score,
        "total_claims": result.total_claims,
        "supported": result.supported_count,
        "partially_supported": result.partial_count,
        "contradicted": result.contradicted_count,
        "conflicting": 0,
        "no_evidence": result.no_evidence_count,
        "verdicts": verdicts,
    }


@router.get("/history", response_model=list[VerificationHistoryItem])
async def get_history(library_id: str | None = None, limit: int = 50):
    db = get_db()
    history = db.get_verification_history(library_id=library_id, limit=limit)
    return [
        {
            "id": v.id,
            "library_id": v.library_id,
            "input_text": v.input_text[:200],
            "trust_score": v.trust_score,
            "claim_count": len(v.claims),
            "created_at": v.created_at.isoformat(),
        }
        for v in history
    ]


@router.get("/{ver_id}")
async def get_verification(ver_id: str):
    db = get_db()
    v = db.get_verification(ver_id)
    if not v:
        raise HTTPException(status_code=404, detail="Verification not found")
    return {
        "id": v.id,
        "library_id": v.library_id,
        "input_text": v.input_text,
        "trust_score": v.trust_score,
        "claims": v.claims,
        "created_at": v.created_at.isoformat(),
    }


@router.get("/{ver_id}/export")
async def export_verification(ver_id: str):
    db = get_db()
    v = db.get_verification(ver_id)
    if not v:
        raise HTTPException(status_code=404, detail="Verification not found")
    return JSONResponse(
        content={
            "id": v.id,
            "library_id": v.library_id,
            "input_text": v.input_text,
            "trust_score": v.trust_score,
            "claims": v.claims,
            "created_at": v.created_at.isoformat(),
            "exported_at": __import__("datetime").datetime.now().isoformat(),
        },
        headers={"Content-Disposition": f"attachment; filename=verification_{ver_id}.json"},
    )


@router.delete("/{ver_id}")
async def delete_verification(ver_id: str):
    db = get_db()
    deleted = db.delete_verification(ver_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Verification not found")
    return {"status": "deleted", "id": ver_id}


@router.post("/{ver_id}/delete")
async def delete_verification_post(ver_id: str):
    """Compatibility delete endpoint for clients/environments that block DELETE."""
    db = get_db()
    deleted = db.delete_verification(ver_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Verification not found")
    return {"status": "deleted", "id": ver_id}


def _to_api_verdict(claim) -> dict:
    verdict_map = {
        Verdict.SUPPORTED: "SUPPORTED",
        Verdict.CONTRADICTED: "CONTRADICTED",
        Verdict.PARTIAL: "PARTIALLY_SUPPORTED",
        Verdict.NO_EVIDENCE: "NO_EVIDENCE",
    }

    return {
        "claim": claim.claim_text,
        "claim_type": "FACTUAL",
        "verdict": verdict_map.get(claim.verdict, "NO_EVIDENCE"),
        "confidence": claim.confidence,
        "reason": claim.reason,
        "reasoning": claim.reason,
        "used_llm": claim.used_llm,
        "evidence": {
            "text": claim.evidence_text,
            "source": claim.evidence_source,
            "page": claim.evidence_page,
        }
        if claim.evidence_source or claim.evidence_text
        else None,
        "evidence_used": claim.evidence_text,
        "contradiction_type": claim.contradiction_type,
        "contradiction_explanation": claim.reason if claim.contradiction_type else None,
        "sources": [
            {
                "document_title": claim.evidence_source,
                "page": claim.evidence_page,
                "paragraph": None,
            }
        ]
        if claim.evidence_source
        else [],
        "temporal_context": None,
    }
