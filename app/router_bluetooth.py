from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from app.services.bluetooth import bluetooth_service

router = APIRouter(prefix="/bluetooth", tags=["bluetooth"])

@router.get("/devices")
def bluetooth_devices():
    items, diagnostics = bluetooth_service.get_devices()
    return {"ok": True, "items": items, "diagnostics": diagnostics}

@router.post("/scan")
def bluetooth_scan(duration: int = 5):
    diagnostics = bluetooth_service.scan(duration=duration)
    return {"ok": diagnostics.get("ok", False), "diagnostics": diagnostics}

@router.post("/pair")
def bluetooth_pair(payload: dict = Body(...)):
    address = payload.get("address")
    if not address:
        raise HTTPException(status_code=400, detail="address is required")
    return {"ok": bluetooth_service.pair_device(address)}

@router.post("/connect")
def bluetooth_connect(payload: dict = Body(...)):
    address = payload.get("address")
    if not address:
        raise HTTPException(status_code=400, detail="address is required")
    return {"ok": bluetooth_service.connect_device(address)}

@router.post("/disconnect")
def bluetooth_disconnect(payload: dict = Body(...)):
    address = payload.get("address")
    if not address:
        raise HTTPException(status_code=400, detail="address is required")
    return {"ok": bluetooth_service.disconnect_device(address)}

@router.post("/forget")
def bluetooth_forget(payload: dict = Body(...)):
    address = payload.get("address")
    if not address:
        raise HTTPException(status_code=400, detail="address is required")
    return {"ok": bluetooth_service.forget_device(address)}
