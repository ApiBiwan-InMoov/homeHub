# app/router_actions.py
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.services.timers import timer_mgr

router = APIRouter(prefix="/actions", tags=["actions"])


def _apply_do(action: dict[str, Any], target: dict[str, Any]):
    if target.get("kind") == "ipx_relay":
        from app.deps import get_ipx

        ipx = get_ipx()
        relay = int(target["relay"])
        t = action.get("type")
        if t == "set_on":
            ipx.set_relay(relay, True)
        if t == "set_off":
            ipx.set_relay(relay, False)
        if t == "toggle":
            ipx.toggle_relay(relay)


@router.post("/relay")
def relay_action(payload: dict[str, Any] = Body(...)):
    """
    Expects:
      {
        "relay": 2,
        "op": "on" | "off" | "toggle",
        "revert_after_s": 600?   // optional
      }
    """
    relay = int(payload["relay"])
    op = payload.get("op", "toggle")
    revert = int(payload.get("revert_after_s", 0)) or None

    # do now
    do = {"type": "set_on" if op == "on" else "set_off" if op == "off" else "toggle"}
    target = {"kind": "ipx_relay", "relay": relay}
    _apply_do(do, target)

    timer_info = None
    if revert:
        # figure out undo
        if do["type"] == "set_on":
            undo = {"type": "set_off"}
        elif do["type"] == "set_off":
            undo = {"type": "set_on"}
        else:
            undo = {"type": "toggle"}  # toggle back after N sec
        job = timer_mgr.schedule(
            duration_s=revert, target=target, do=do, undo=undo, origin={"kind": "api", "note": "relay_action"}
        )
        timer_info = {"id": job.id, "remaining_s": job.duration_s, "total_s": job.duration_s}

    return {"ok": True, "timer": timer_info}


@router.get("/timers")
def list_timers():
    return {"items": timer_mgr.list_active()}


@router.delete("/timers/{job_id}")
def cancel_timer(job_id: str):
    return {"ok": timer_mgr.cancel(job_id)}
