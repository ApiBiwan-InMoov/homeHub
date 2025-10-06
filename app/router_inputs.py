# app/router_inputs.py
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .deps import get_ipx
from .ipx800.client import IPX_ANALOG_RESOLUTION, IPX_ANALOG_VREF
from .sensors.analog import convert_value_from_config
from .services.poller import current_meta, current_state
from .storage.analog_config import load_analog_cfg, save_analog_cfg
from .storage.inputs import (
    load_an_names,
    load_btn_names,
    save_an_names,
    save_btn_names,
)

router = APIRouter(prefix="/inputs", tags=["inputs"])
templates = Jinja2Templates(directory="app/ui/templates")


def _to_state_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        try:
            return obj.model_dump()
        except Exception:
            pass
    try:
        return dict(obj)
    except Exception:
        return {}


def _clamp_pad_bool(arr: list[bool], size: int) -> list[bool]:
    arr = list(arr[:size])
    if len(arr) < size:
        arr.extend([False] * (size - len(arr)))
    return arr


def _clamp_pad_optfloat(arr: list[float | None], size: int) -> list[float | None]:
    arr = list(arr[:size])
    if len(arr) < size:
        arr.extend([None] * (size - len(arr)))
    return arr


# ---------- Models for config ----------


class AnalogCfgItem(BaseModel):
    mode: Literal["voltage", "counts", "mv", "scale_0_10v", "linear_from_volts", "current_4_20ma", "ntc_beta"] = (
        "voltage"
    )
    unit: str | None = Field(default=None, description="Display unit (e.g., '°C', 'bar', '%')")
    decimals: int = 2
    params: dict[str, Any] = Field(default_factory=dict)


class AnalogCfgUpdate(BaseModel):
    index: int
    cfg: AnalogCfgItem


# ---------- JSON: status (with conversion) ----------


@router.get("/status")
def inputs_status(
    ipx=Depends(get_ipx),
    max_buttons: int = 32,
    max_analogs: int = 16,
):
    st = _to_state_dict(current_state())
    meta = _to_state_dict(current_meta())

    digital_raw = st.get("digital") or []
    analog_raw = st.get("analog") or []

    try:
        digital_list: list[bool] = [bool(x) for x in list(digital_raw)]
    except Exception:
        digital_list = []
    try:
        analog_volts: list[float | None] = [(None if x is None else float(x)) for x in list(analog_raw)]
    except Exception:
        analog_volts = []

    # Live fallback if poller empty
    need_live = (not digital_list and not analog_volts) or all(v is None for v in analog_volts[:max_analogs])
    if need_live:
        try:
            live_d = ipx.get_inputs(max_buttons=max_buttons, max_analogs=max_analogs) or []
            live_a = ipx.get_analogs(max_analogs=max_analogs) or []
            if live_d:
                digital_list = [bool(x) for x in live_d]
            if any(v is not None for v in live_a):
                analog_volts = [v for v in live_a]
        except Exception:
            pass

    digital = _clamp_pad_bool(digital_list, max_buttons)
    analog_volts = _clamp_pad_optfloat(analog_volts, max_analogs)

    # Load names + per-channel conversion configs
    btn_names = load_btn_names(max_buttons)
    an_names = load_an_names(max_analogs)
    cfg_list = load_analog_cfg(max_analogs)

    analog_display = []
    for i in range(max_analogs):
        volts = analog_volts[i] if i < len(analog_volts) else None
        cfg = cfg_list[i] if i < len(cfg_list) else {}
        value, unit, decimals = convert_value_from_config(
            volts,
            cfg,
            vref_env=IPX_ANALOG_VREF,
            adc_res_env=IPX_ANALOG_RESOLUTION,
        )
        if value is None:
            text = "—"
        else:
            fmt = f"{{:.{decimals}f}}"
            text = f"{fmt.format(value)}{(' ' + unit) if unit else ''}"
        analog_display.append(
            {
                "index": i,
                "name": an_names[i],
                "volts": volts,
                "value": value,
                "unit": unit,
                "decimals": decimals,
                "text": text,
                "mode": cfg.get("mode", "voltage"),
            }
        )

    return {
        "meta": meta,
        "digital": [{"index": i, "on": digital[i], "name": btn_names[i]} for i in range(max_buttons)],
        "analog": analog_display,
    }


# ---------- Names (already supported) ----------


class NameUpdate(BaseModel):
    type: Literal["digital", "analog"]
    index: int
    name: str | None = None


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


# ---------- Analog config endpoints ----------
@router.get("/config", response_class=HTMLResponse)
def inputs_config_page(request: Request):
    return templates.TemplateResponse("inputs_config.html", {"request": request})


@router.get("/config/analogs")
def get_analog_config(max_analogs: int = 16):
    return {"configs": load_analog_cfg(max_analogs)}


@router.post("/config/analog")
def set_analog_config(update: AnalogCfgUpdate, max_analogs: int = 16):
    if not (0 <= update.index < max_analogs):
        raise HTTPException(400, "index out of range")
    cfgs = load_analog_cfg(max_analogs)
    cfgs[update.index] = update.cfg.dict()
    save_analog_cfg(cfgs)
    return {"ok": True, "index": update.index, "cfg": update.cfg}
