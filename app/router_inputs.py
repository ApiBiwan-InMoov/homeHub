from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List, Literal, Dict, Any

from .services.poller import current_state  

from .deps import get_ipx
from .storage.inputs import load_btn_names, save_btn_names, load_an_names, save_an_names
from .storage.rules import load_rules, add_rule, update_rule, delete_rule
from .storage.logs import read_recent, append_log
from .services.poller import current_state, current_meta

router = APIRouter(prefix="/inputs", tags=["inputs"])
templates = Jinja2Templates(directory="app/ui/templates")

# ----- JSON: inputs -----



@router.get("/status")
def inputs_status(max_buttons: int = 32, max_analogs: int = 16):
    st = current_state()
    meta = current_meta()

    digital = (st.get("digital") or [])
    analog  = (st.get("analog")  or [])

    # pad/truncate to requested sizes
    digital = (digital[:max_buttons] + [False]*max(0, max_buttons-len(digital)))
    analog  = (analog[:max_analogs] + [None]*max(0, max_analogs-len(analog)))

    from .storage.inputs import load_btn_names, load_an_names
    btn_names = load_btn_names(max_buttons)
    an_names  = load_an_names(max_analogs)

    return {
        "meta": meta,
        "digital": [{"index": i, "on": bool(digital[i]), "name": btn_names[i]} for i in range(max_buttons)],
        "analog":  [{"index": i, "value": analog[i],     "name": an_names[i]}  for i in range(max_analogs)],
    }


class NameUpdate(BaseModel):
    type: Literal["digital","analog"]
    index: int
    name: Optional[str] = None

@router.post("/name")
def set_input_name(update: NameUpdate, max_buttons: int = 32, max_analogs: int = 16):
    if update.type == "digital":
        names = load_btn_names(max_buttons)
        if not (0 <= update.index < max_buttons):
            raise HTTPException(400, "index out of range")
        names[update.index] = update.name or None
        save_btn_names(names)
    else:
        names = load_an_names(max_analogs)
        if not (0 <= update.index < max_analogs):
            raise HTTPException(400, "index out of range")
        names[update.index] = update.name or None
        save_an_names(names)
    return {"ok": True}

# ----- Rules -----
class Action(BaseModel):
    type: Literal["toggle_relay","set_relay_on","set_relay_off","webhook"]
    relay: Optional[int] = None
    url: Optional[str] = None
    payload: Optional[dict] = None

class Rule(BaseModel):
    id: Optional[str] = None
    enabled: bool = True
    input_type: Literal["digital","analog"]
    index: int
    trigger: Literal["on_rising","on_falling","on_change","above","below","cross_up","cross_down"]
    threshold: Optional[float] = None
    cooldown_seconds: Optional[float] = 0
    actions: List[Action] = []

@router.get("/rules")
def get_rules():
    return load_rules()

@router.post("/rules")
def create_rule(rule: Rule):
    if rule.input_type == "analog" and rule.trigger in ("on_rising","on_falling","on_change"):
        raise HTTPException(400, "Use above/below/cross_* for analog")
    if rule.input_type == "digital" and rule.trigger not in ("on_rising","on_falling","on_change"):
        raise HTTPException(400, "Use digital triggers for digital inputs")
    return add_rule(rule.dict())

@router.put("/rules/{rule_id}")
def patch_rule(rule_id: str, patch: Dict[str, Any]):
    r = update_rule(rule_id, patch)
    if not r:
        raise HTTPException(404, "rule not found")
    return r

@router.delete("/rules/{rule_id}")
def remove_rule(rule_id: str):
    if not delete_rule(rule_id):
        raise HTTPException(404, "rule not found")
    return {"ok": True}

# Test a rule immediately (ignores trigger, runs actions)
@router.post("/rules/{rule_id}/test")
def test_rule(rule_id: str, ipx = Depends(get_ipx)):
    data = load_rules()
    r = next((x for x in data.get("rules", []) if x.get("id")==rule_id), None)
    if not r:
        raise HTTPException(404, "rule not found")
    # Perform actions
    from .services.poller import _apply_actions  # type: ignore
    import asyncio
    asyncio.create_task(_apply_actions(ipx, r.get("actions", []), reason="manual_test", rule_id=rule_id))
    append_log({"type":"manual_test","rule_id":rule_id})
    return {"ok": True}

# ----- Logs -----
@router.get("/logs")
def get_logs(limit: int = 200):
    return {"events": read_recent(limit)}

# ----- UI -----
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def inputs_page(request: Request):
    return templates.TemplateResponse("inputs.html", {"request": request})

