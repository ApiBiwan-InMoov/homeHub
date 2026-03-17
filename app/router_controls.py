from fastapi import APIRouter, Depends

from .config import settings
from .deps import get_ipx

router = APIRouter(prefix="/control", tags=["control"])


@router.post("/lights/{state}")
def set_lights(state: str, ipx=Depends(get_ipx)):
    on = state.lower() == "on"
    ipx.set_relay(settings.ipx_lights_relay, on)
    return {"ok": True, "lights": on}


@router.post("/heating/{state}")
def set_heating(state: str, ipx=Depends(get_ipx)):
    on = state.lower() == "on"
    ipx.set_relay(settings.ipx_heating_relay, on)
    return {"ok": True, "heating": on}


@router.post("/toggle/{device}")
def toggle(device: str, ipx=Depends(get_ipx)):
    if device == "lights":
        ok = ipx.toggle_relay(settings.ipx_lights_relay)
    elif device == "heating":
        ok = ipx.toggle_relay(settings.ipx_heating_relay)
    else:
        return {"ok": False, "error": "unknown device"}
    return {"ok": ok}
