from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.services.llm import LLMClient, LLMConfig, LLMNotConfigured, LLMUnavailable

router = APIRouter(prefix="/llm", tags=["llm"])
templates = Jinja2Templates(directory="app/ui/templates")


def _client() -> LLMClient:
    cfg = LLMConfig(
        provider=settings.llm_provider,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
        system_prompt=settings.llm_system_prompt,
    )
    return LLMClient(cfg)


@router.get("/info", response_class=JSONResponse)
def llm_info(check: bool = Query(False, description="Ping provider to report status")):
    client = _client()
    info = client.info(check=check)
    info.setdefault("recommended_model", "mistral")
    return info


@router.get("/health", response_class=JSONResponse)
def llm_health():
    client = _client()
    try:
        health = client.health()
    except LLMNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except LLMUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "health": health}


@router.post("/generate", response_class=JSONResponse)
def llm_generate(payload: dict = Body(...)):
    prompt = payload.get("prompt") or payload.get("message") or payload.get("text")
    if not prompt or not str(prompt).strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    temperature = payload.get("temperature", 0.7)
    max_tokens = payload.get("max_tokens") or payload.get("maxTokens") or 256
    system = payload.get("system")

    client = _client()
    try:
        res = client.generate(prompt=str(prompt), system=system, temperature=float(temperature), max_tokens=int(max_tokens))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LLMNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except LLMUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, **res}


@router.get("/mcp/manifest", response_class=JSONResponse)
def llm_mcp_manifest():
    """Lightweight manifest to help MCP agents discover endpoints."""
    return {
        "name": "homehub-llm",
        "version": "1.0",
        "description": "Local LLM (French-friendly) for HomeHub and MCP agents",
        "endpoints": {
            "info": "/llm/info",
            "health": "/llm/health",
            "generate": "/llm/generate",
        },
        "provider": settings.llm_provider,
        "model": settings.llm_model,
    }


@router.get("/ui", response_class=HTMLResponse)
@router.get("/config/ui", response_class=HTMLResponse)
def llm_config_ui(request: Request):
    return templates.TemplateResponse("llm_config.html", {"request": request})
