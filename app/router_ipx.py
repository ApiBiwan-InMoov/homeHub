# app/router_ipx.py
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional

from .deps import get_ipx
from .storage.names import load_names, save_names

router = APIRouter(prefix="/ipx", tags=["ipx"])
templates = Jinja2Templates(directory="app/ui/templates")

@router.get("/status")
def ipx_status_json(ipx = Depends(get_ipx), max_relays: int = 16):
    states = ipx.get_outputs(max_relays=max_relays)
    names  = load_names(max_relays=max_relays)
    return {
        "count": len(states),
        "relays": [
            {"relay": i + 1, "on": bool(states[i]), "name": (names[i] if i < len(names) else None)}
            for i in range(min(max_relays, len(states)))
        ],
    }

class NameUpdate(BaseModel):
    relay: int
    name: Optional[str] = None

@router.get("/names")
def get_names(max_relays: int = 32):
    return {"names": load_names(max_relays)}

@router.post("/names")
def set_name(update: NameUpdate, max_relays: int = 32):
    if not (1 <= update.relay <= max_relays):
        raise HTTPException(400, "relay out of range")
    names = load_names(max_relays)
    names[update.relay - 1] = (update.name or None)
    save_names(names)
    return {"ok": True, "relay": update.relay, "name": names[update.relay - 1]}

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def ipx_status_page(request: Request):
    return templates.TemplateResponse("ipx_status.html", {"request": request})
    
    
@router.get("/status_raw")
def ipx_status_raw(ipx = Depends(get_ipx), max_buttons: int = 8, max_relays: int = 8, max_analogs: int = 8):
    # Fetch raw XML and parse the first few fields we care about
    import xml.etree.ElementTree as ET
    r = ipx.session.get(f"{ipx.base}/status.xml", auth=ipx.auth, timeout=2)
    text = r.text if r.ok else ""
    try:
        root = ET.fromstring(text)
    except Exception:
        root = None

    sample = {
        "led":   {f"led{i}": (root.find(f"led{i}").text if (root is not None and root.find(f"led{i}") is not None) else None) for i in range(max_relays)},
        "btn":   {f"btn{i}": (root.find(f"btn{i}").text if (root is not None and root.find(f"btn{i}") is not None) else None) for i in range(max_buttons)},
        "an":    {f"an{i+1}": (root.find(f"an{i+1}").text if (root is not None and root.find(f"an{i+1}") is not None) else None) for i in range(max_analogs)},
        "an0":   {f"an{i}": (root.find(f"an{i}").text if (root is not None and root.find(f"an{i}") is not None) else None) for i in range(max_analogs)},
    }
    return {
        "http_ok": r.ok,
        "length": len(text),
        "snippet": text[:800],
        "sample": sample,
    }

