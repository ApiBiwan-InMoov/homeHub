from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .storage.logs import clear_logs, load_logs

router = APIRouter(prefix="/logs", tags=["logs"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("", response_class=JSONResponse)
def list_logs(
    limit: int = Query(200, ge=1, le=1000),
    type_: str | None = Query(None, alias="type", description="Filter by entry type"),
    q: str | None = Query(None, description="Substring search across the JSON entry"),
):
    """Return recent logs in newest-first order, with optional filtering."""
    # Load a bit more than requested so filtered results are not empty too quickly
    raw_limit = min(1000, max(limit, limit * 3))
    logs = load_logs(raw_limit)

    type_norm = type_.lower() if type_ else None
    q_norm = q.lower() if q else None

    out = []
    for entry in logs:
        if type_norm:
            if str(entry.get("type", "")).lower() != type_norm:
                continue
        if q_norm:
            try:
                hay = json.dumps(entry, ensure_ascii=False).lower()
            except Exception:
                hay = str(entry).lower()
            if q_norm not in hay:
                continue
        out.append(entry)
        if len(out) >= limit:
            break

    return {"logs": out}


@router.delete("", response_class=JSONResponse)
def delete_logs():
    """Clear all logs."""
    clear_logs()
    return {"ok": True}


@router.get("/ui", response_class=HTMLResponse)
def logs_ui(request: Request):
    """Render the log viewer UI."""
    return templates.TemplateResponse("logs.html", {"request": request})