# app/router_ipx_inputs.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .deps import get_ipx

router = APIRouter(prefix="/inputs", tags=["inputs"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("", response_class=HTMLResponse, summary="Inputs UI")
def inputs_page(request: Request):
    # renders app/ui/templates/inputs.html
    return templates.TemplateResponse("inputs.html", {"request": request})


@router.get("/status", summary="Current IPX inputs (JSON)")
def inputs_status(
    ipx=Depends(get_ipx),
    max_buttons: int = Query(32, ge=0, le=128),
    max_analogs: int = Query(16, ge=0, le=128),
):
    """
    Returns normalized inputs from the IPX client.
    Your IPX client should implement .get_inputs(max_buttons=..., max_analogs=...)
    and return something like:
      {"digital": [0/1,...], "analog": [float,...]}
    """
    return ipx.get_inputs(max_buttons=max_buttons, max_analogs=max_analogs)


@router.get("/raw", summary="Raw IPX status (best-effort JSON)")
def inputs_raw(ipx=Depends(get_ipx)):
    """
    Optional endpoint in case your client exposes a raw call.
    If not available, we fall back to /status output.
    """
    raw = getattr(ipx, "raw_status", None)
    if callable(raw):
        return raw()
    return ipx.get_inputs(max_buttons=32, max_analogs=16)
