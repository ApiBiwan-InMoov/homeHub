from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.services.llm import LLMClient, LLMConfig, LLMNotConfigured, LLMUnavailable
from app.storage.llm_storage import (
    AVAILABLE_TOOLS,
    DEFAULT_MANIFEST,
    build_system_prompt,
    load_llm_config,
    load_llm_manifest,
    save_llm_config,
    save_llm_manifest,
)

router = APIRouter(prefix="/llm", tags=["llm"])
templates = Jinja2Templates(directory="app/ui/templates")


def _client() -> LLMClient:
    stored = load_llm_config()
    merged_system = build_system_prompt(stored)
    cfg = LLMConfig(
        provider=settings.llm_provider,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
        system_prompt=merged_system or settings.llm_system_prompt,
    )
    return LLMClient(cfg)


@router.get("/info", response_class=JSONResponse)
def llm_info(check: bool = Query(False, description="Ping provider to report status")):
    client = _client()
    info = client.info(check=check)
    info.setdefault("recommended_model", "mistral")
    cfg = load_llm_config()
    info["config"] = cfg
    info["manifest"] = load_llm_manifest()
    return info


@router.get("/config", response_class=JSONResponse)
def llm_config_get():
    return {"config": load_llm_config()}


@router.post("/config", response_class=JSONResponse)
def llm_config_set(payload: dict = Body(...)):
    current = load_llm_config()
    new_cfg = {
        "system_prompt": payload.get("system_prompt") or payload.get("systemPrompt") or current.get("system_prompt"),
        "constraints": payload.get("constraints", current.get("constraints")),
    }
    saved = save_llm_config(new_cfg)
    return {"ok": True, "config": saved}


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

    cfg = load_llm_config()
    client = _client()
    try:
        res = client.generate(
            prompt=str(prompt),
            system=system or build_system_prompt(cfg) or settings.llm_system_prompt,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LLMNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except LLMUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, **res}


@router.get("/mcp/manifest", response_class=JSONResponse)
def llm_mcp_manifest():
    """Manifest pour agents MCP (inclut les tools configurables)."""
    manifest = load_llm_manifest()
    manifest.setdefault("endpoints", {})
    manifest["endpoints"].setdefault("info", "/llm/info")
    manifest["endpoints"].setdefault("health", "/llm/health")
    manifest["endpoints"].setdefault("generate", "/llm/generate")
    manifest["provider"] = settings.llm_provider
    manifest["model"] = settings.llm_model
    return manifest


@router.get("/manifest/config", response_class=JSONResponse)
def llm_manifest_get():
    return {"manifest": load_llm_manifest(), "available_tools": AVAILABLE_TOOLS}


@router.post("/manifest/config", response_class=JSONResponse)
def llm_manifest_set(payload: dict = Body(...)):
    incoming = payload.get("manifest", payload)
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="manifest must be an object")
    saved = save_llm_manifest(incoming)
    return {"ok": True, "manifest": saved}


@router.get("/ui", response_class=HTMLResponse)
@router.get("/config/ui", response_class=HTMLResponse)
def llm_config_ui(request: Request):
    return templates.TemplateResponse("llm_config.html", {"request": request})


@router.get("/manifest/ui", response_class=HTMLResponse)
def llm_manifest_ui(request: Request):
    return templates.TemplateResponse("llm_manifest.html", {"request": request})
