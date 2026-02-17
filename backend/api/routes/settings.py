"""Settings routes — LLM config and connections."""

import json
from fastapi import APIRouter, HTTPException
from backend.api.schemas import LLMSettingsUpdate, TestResult
from backend.main import get_db, get_llm, reload_llm

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_settings():
    db = get_db()
    all_settings = db.get_all_settings()

    # Parse LLM settings
    llm_config = {}
    try:
        llm_config = json.loads(all_settings.get("llm_config", "{}"))
    except json.JSONDecodeError:
        pass

    # Parse connection configs
    connections = {}
    for key, value in all_settings.items():
        if key.startswith("connection_"):
            conn_type = key.replace("connection_", "")
            try:
                connections[conn_type] = json.loads(value)
            except json.JSONDecodeError:
                pass

    return {
        "llm": llm_config,
        "connections": connections,
    }


@router.put("/llm")
async def update_llm_settings(body: LLMSettingsUpdate):
    db = get_db()
    config = body.model_dump(exclude_none=True)
    db.set_setting("llm_config", json.dumps(config))

    # Reload the LLM provider with new config
    reload_llm(config)

    return {"status": "saved", "config": config}


@router.post("/llm/test", response_model=TestResult)
async def test_llm():
    llm = get_llm()
    result = await llm.test_connection()
    if result["status"] == "ok":
        embed_result = await llm.test_embeddings()
        return {
            "status": "ok",
            "message": f"Chat: OK | Embeddings: {embed_result['status']} (dim={embed_result.get('dimensions', '?')})",
        }
    return {"status": "error", "error": result.get("error", "Connection failed")}


@router.put("/connections/{conn_type}")
async def update_connection(conn_type: str, config: dict):
    return {
        "status": "unsupported",
        "message": "External connector settings are disabled in local-first mode.",
    }


@router.post("/connections/test", response_model=TestResult)
async def test_connection(config: dict):
    """External connection tests are disabled for local-first mode."""
    return {
        "status": "error",
        "error": "External connector tests are disabled in local-first mode.",
    }
