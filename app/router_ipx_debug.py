# app/router_ipx_debug.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.deps import get_ipx
from app.ipx800.client import debug_extract_tags

from .services.poller import current_meta, current_state

router = APIRouter(prefix="/ipx/debug", tags=["ipx-debug"])


def _to_state_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return obj.dict()  # pydantic v1
        except Exception:
            pass
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        try:
            return obj.model_dump()  # pydantic v2
        except Exception:
            pass
    try:
        return dict(obj)  # type: ignore[arg-type]
    except Exception:
        return {}


@router.get("/status-xml")
def status_xml(ipx=Depends(get_ipx), max_buttons: int = 32, max_analogs: int = 16):
    xml = ipx.get_raw_status_xml()
    tags = debug_extract_tags(xml, max_buttons=max_buttons, max_analogs=max_analogs)
    return {"xml": xml, "tags": tags}


@router.get("/parsed")
def parsed(ipx=Depends(get_ipx), max_buttons: int = 32, max_analogs: int = 16, max_relays: int = 32):
    return {
        "digital": ipx.get_inputs(max_buttons=max_buttons),
        "analog": ipx.get_analogs(max_analogs=max_analogs),
        "outputs": ipx.get_outputs(max_relays=max_relays),
    }


@router.get("/poller-state")
def poller_state():
    st = _to_state_dict(current_state())
    meta = _to_state_dict(current_meta())
    return {"state": st, "meta": meta}
