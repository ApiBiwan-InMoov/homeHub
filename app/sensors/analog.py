# app/sensors/analog.py
from __future__ import annotations

import math
from typing import Any

# Fallbacks if caller doesn’t pass env
DEFAULT_VREF = 3.3
DEFAULT_RES = 1023


def _round_or_none(x: float | None, decimals: int) -> float | None:
    if x is None:
        return None
    try:
        return round(x, decimals)
    except Exception:
        return x


def convert_value_from_config(
    volts: float | None,
    cfg: dict[str, Any],
    *,
    vref_env: float = DEFAULT_VREF,
    adc_res_env: int = DEFAULT_RES,
) -> tuple[float | None, str, int]:
    """
    Returns: (converted_value, unit, decimals)
    Modes:
      - voltage                       → value=volts, unit from cfg.unit
      - counts                        → value=volts * RES / VREF, unit="counts" (unless cfg.unit overrides)
      - mv                            → value=volts*1000, unit="mV"
      - scale_0_10V (out_min,out_max) → map 0..10 V to [out_min..out_max]
      - linear_from_volts (a,b)       → value=a*volts + b
      - current_4_20mA (shunt_ohms,out_min,out_max) → V=I*R; map 4..20 mA to out range
      - ntc_beta (beta,r_series,r0,t0_c[,vref])     → °C from divider (pull-up R_series to Vref)
    """
    mode = (cfg.get("mode") or "voltage").lower()
    unit = str(cfg.get("unit") or ("V" if mode == "voltage" else ""))
    decimals = int(cfg.get("decimals") or 2)
    params = cfg.get("params") or {}

    if volts is None:
        return (None, unit or "", decimals)

    vref = float(params.get("vref", vref_env))
    adc_res = int(params.get("adc_res", adc_res_env))

    if mode == "voltage":
        return (_round_or_none(volts, decimals), unit or "V", decimals)

    if mode == "counts":
        counts = volts * adc_res / max(vref, 1e-9)
        return (_round_or_none(counts, decimals), unit or "counts", decimals)

    if mode == "mv":
        mv = volts * 1000.0
        return (_round_or_none(mv, decimals), unit or "mV", decimals)

    if mode == "scale_0_10v":
        out_min = float(params.get("out_min", 0.0))
        out_max = float(params.get("out_max", 100.0))
        val = (max(min(volts, 10.0), 0.0) / 10.0) * (out_max - out_min) + out_min
        return (_round_or_none(val, decimals), unit or "", decimals)

    if mode == "linear_from_volts":
        a = float(params.get("a", 1.0))
        b = float(params.get("b", 0.0))
        val = a * volts + b
        return (_round_or_none(val, decimals), unit or "", decimals)

    if mode == "current_4_20ma":
        shunt = float(params.get("shunt_ohms", 150.0))  # e.g., 150Ω → 4–20mA → 0.6–3.0V
        out_min = float(params.get("out_min", 0.0))
        out_max = float(params.get("out_max", 100.0))
        curr_amps = volts / max(shunt, 1e-9)
        curr_ma = curr_amps * 1000.0
        # normalize 4..20 mA
        pct = (curr_ma - 4.0) / 16.0
        pct = 0.0 if pct < 0 else 1.0 if pct > 1 else pct
        val = out_min + pct * (out_max - out_min)
        return (_round_or_none(val, decimals), unit or "", decimals)

    if mode == "ntc_beta":
        # Beta model, divider with pull-up R_series to Vref, NTC to GND, reading Vout @ junction
        beta = float(params.get("beta", 3950.0))
        r_series = float(params.get("r_series", 10000.0))
        r0 = float(params.get("r0", 10000.0))
        t0_c = float(params.get("t0_c", 25.0))  # °C
        # compute ntc resistance
        if volts <= 0 or volts >= vref:
            return (None, unit or "°C", decimals)
        r_ntc = r_series * volts / (vref - volts)
        # Beta formula
        t0_k = t0_c + 273.15
        try:
            t_k = 1.0 / ((1.0 / t0_k) + (1.0 / beta) * math.log(r_ntc / r0))
            t_c = t_k - 273.15
        except (ValueError, ZeroDivisionError):
            t_c = None
        return (_round_or_none(t_c, decimals), unit or "°C", decimals)

    # Unknown mode → return volts unchanged
    return (_round_or_none(volts, decimals), unit or "V", decimals)
