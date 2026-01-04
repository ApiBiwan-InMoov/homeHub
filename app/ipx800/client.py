# app/ipx800/client.py
from __future__ import annotations

import logging
import os
import re

from xml.etree import ElementTree as ET

import requests

__all__ = [
    "IPX800Client",
    "debug_extract_tags",
]

logger = logging.getLogger(__name__)

# ---------------------------
# Environment / defaults
# ---------------------------

IPX_HOST = os.getenv("IPX_HOST", "192.168.0.10")
IPX_PORT = int(os.getenv("IPX_PORT", "80"))
IPX_USER = os.getenv("IPX_USER", "") or None
IPX_PASSWORD = os.getenv("IPX_PASSWORD", "") or None
IPX_STATUS_PATH = os.getenv("IPX_STATUS_PATH", "/status.xml")

IPX_HTTP_TIMEOUT = float(os.getenv("IPX_HTTP_TIMEOUT", "5.0"))
IPX_HTTP_VERIFY_TLS = os.getenv("IPX_HTTP_VERIFY_TLS", "true").lower() not in ("0", "false", "no")

# Digital / analog maximums (safe defaults for IPX800 v3)
IPX_MAX_BUTTONS = int(os.getenv("IPX_MAX_BUTTONS", "32"))
IPX_MAX_ANALOGS = int(os.getenv("IPX_MAX_ANALOGS", "16"))

# Analogue normalization:
# - auto  : detect counts/mV/V and convert to volts
# - volts : treat incoming numbers as "raw counts" and convert to volts using VREF/RES
# - raw   : pass-through numbers (no scaling)
IPX_ANALOG_MODE = os.getenv("IPX_ANALOG_MODE", "auto").lower()  # auto|volts|raw
IPX_ANALOG_VREF = float(os.getenv("IPX_ANALOG_VREF", "3.3"))
IPX_ANALOG_RESOLUTION = int(os.getenv("IPX_ANALOG_RESOLUTION", "1023"))  # 10-bit 0..1023, 12-bit 0..4095

# ---------------------------
# Helpers
# ---------------------------

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _strip_control_chars(s: str) -> str:
    return _CONTROL_CHARS.sub("", s)


def _safe_parse_xml(xml_text: str) -> ET.Element:
    try:
        return ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        cleaned = _strip_control_chars(xml_text)
        return ET.fromstring(cleaned.encode("utf-8"))


def _element_text(root: ET.Element, name: str) -> str | None:
    el = root.find(name)
    if el is not None and el.text is not None:
        return el.text
    return None


def _find_any_text(root: ET.Element, names: tuple[str, ...]) -> str | None:
    for nm in names:
        val = _element_text(root, nm)
        if val is not None:
            return val
    return None


def _btn_txt_to_bool(txt: str | None) -> bool:
    if not txt:
        return False
    t = txt.strip().lower()
    # many firmwares use "down"/"up", some use 1/0 or on/off
    return t in ("down", "1", "on", "pressed", "true")


def _relay_txt_to_bool(txt: str | None) -> bool:
    if not txt:
        return False
    t = txt.strip().lower()
    return t in ("1", "on", "true", "closed", "energized")


def _parse_number(txt: str | None) -> float | None:
    """Parse floats or ints, tolerate decimal comma."""
    if txt is None:
        return None
    t = txt.strip().replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        try:
            return float(int(t))
        except Exception:
            return None


def _normalize_analog(x: float | None) -> float | None:
    """Return volts (rounded) in modes 'auto' and 'volts'; pass-through for 'raw'."""
    if x is None:
        return None
    mode = IPX_ANALOG_MODE
    vref = IPX_ANALOG_VREF
    res = IPX_ANALOG_RESOLUTION

    if mode == "raw":
        return x

    if mode == "volts":
        # treat incoming x as raw counts
        return round((x * vref) / float(res), 3)

    # auto:
    # counts -> volts
    if 0 <= x <= res:
        return round((x * vref) / float(res), 3)
    # mV -> volts
    if 0 <= x <= (vref * 1000.0 + 50.0):
        return round(x / 1000.0, 3)
    # already volts (or unknown but plausible)
    return round(x, 3)


# ---------------------------
# Parsers (robust to 0/1-based & aliases)
# ---------------------------


def _parse_digitals_bool(root: ET.Element, max_buttons: int) -> list[bool]:
    """Return list[bool] for digital inputs."""
    vals: list[bool] = []

    # Pass 1: 0-based btn0..btn(N-1)
    found_any = False
    tmp: list[str | None] = []
    for i in range(max_buttons):
        tmp.append(_element_text(root, f"btn{i}"))
        if tmp[-1] is not None:
            found_any = True

    if not found_any:
        # Pass 2: 1-based btn1..btnN -> map to 0..N-1
        tmp = []
        for i1 in range(1, max_buttons + 1):
            tmp.append(_element_text(root, f"btn{i1}"))
            if tmp[-1] is not None:
                found_any = True

    if not found_any:
        # Pass 3: aliases (some variants seen in the wild)
        tmp = []
        # try 0-based aliases first
        aliases_zero = ("input{}", "in{}", "din{}")
        for i in range(max_buttons):
            txt = _find_any_text(root, tuple(a.format(i) for a in aliases_zero))
            tmp.append(txt)
            if txt is not None:
                found_any = True
        if not found_any:
            # 1-based alias fallback
            tmp = []
            for i1 in range(1, max_buttons + 1):
                txt = _find_any_text(root, tuple(a.format(i1) for a in aliases_zero))
                tmp.append(txt)
                if txt is not None:
                    found_any = True

    for raw in tmp:
        vals.append(_btn_txt_to_bool(raw))
    # pad just in case
    if len(vals) < max_buttons:
        vals.extend([False] * (max_buttons - len(vals)))
    return vals


def _parse_analogs_volts(root: ET.Element, max_analogs: int) -> list[float | None]:
    """Return list[float | None] -> volts (in auto/volts modes) or raw in 'raw' mode.
    Supports tags: an{n}, ana{n}, analog{n} (0-based & 1-based)."""
    values: list[float | None] = [None] * max_analogs

    # Pass A: 1-based first
    found_any = False
    for i1 in range(1, max_analogs + 1):
        raw = _find_any_text(root, (f"an{i1}", f"ana{i1}", f"analog{i1}"))
        val = _parse_number(raw)
        if val is not None:
            found_any = True
        values[i1 - 1] = _normalize_analog(val)

    # Pass B: 0-based fallback
    if not found_any:
        values = [None] * max_analogs
        for i0 in range(max_analogs):
            raw = _find_any_text(root, (f"an{i0}", f"ana{i0}", f"analog{i0}"))
            val = _parse_number(raw)
            values[i0] = _normalize_analog(val)

    return values


def _parse_outputs_bool(root: ET.Element, max_relays: int) -> list[bool]:
    """Return list[bool] for relay/output states."""
    out: list[bool] = [False] * max_relays

    # Preferred: ledX 0-based
    found_any = False
    for idx0 in range(max_relays):
        txt = _element_text(root, f"led{idx0}")
        if txt is not None:
            found_any = True
        out[idx0] = _relay_txt_to_bool(txt)

    # 1-based fallback: led1..ledN
    if not found_any:
        out = [False] * max_relays
        for relay in range(1, max_relays + 1):
            txt = _element_text(root, f"led{relay}")
            out[relay - 1] = _relay_txt_to_bool(txt)

    # Aliases (0-based then 1-based) if nothing found so far
    if not found_any:
        aliases_zero = ("relay{}", "out{}", "rly{}")
        tmp_found = False
        out = [False] * max_relays
        for i in range(max_relays):
            txt = _find_any_text(root, tuple(a.format(i) for a in aliases_zero))
            if txt is not None:
                tmp_found = True
            out[i] = _relay_txt_to_bool(txt)
        if not tmp_found:
            out = [False] * max_relays
            for i1 in range(1, max_relays + 1):
                txt = _find_any_text(root, tuple(a.format(i1) for a in aliases_zero))
                out[i1 - 1] = _relay_txt_to_bool(txt)

    return out


# ---------------------------
# Client (SYNC)
# ---------------------------


class IPX800Client:
    """
    Fully synchronous client compatible with your current routes & poller.

    Exposed methods:
      - get_outputs(max_relays)  -> list[bool]
      - get_inputs(max_buttons)  -> list[bool]
      - get_analogs(max_analogs) -> list[float | None]  (volts by default)
      - get_status(...)          -> dict(digital=[...], analog=[...])
    """

    def __init__(
        self,
        host: str = IPX_HOST,
        port: int = IPX_PORT,
        user: str | None = IPX_USER,
        password: str | None = IPX_PASSWORD,
        status_path: str = IPX_STATUS_PATH,
        timeout: float = IPX_HTTP_TIMEOUT,
        verify_tls: bool = IPX_HTTP_VERIFY_TLS,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.status_path = status_path if status_path.startswith("/") else f"/{status_path}"
        self.timeout = timeout
        self.verify_tls = verify_tls

        scheme = "https" if self.port == 443 else "http"
        self.base_url = f"{scheme}://{self.host}:{self.port}"
        # Maintain backward compatibility with legacy code/tests that
        # referenced the ``base`` attribute directly.
        self.base = self.base_url

    # ---- Public API (sync) ----

    # AFTER (accept & ignore extra kwargs like max_analogs on get_inputs)
    def get_outputs(self, max_relays: int = 32, **_) -> list[bool]:
        root = self._fetch_status_root()
        return _parse_outputs_bool(root, max_relays=max_relays)

    def get_inputs(self, max_buttons: int = IPX_MAX_BUTTONS, **_) -> list[bool]:
        root = self._fetch_status_root()
        return _parse_digitals_bool(root, max_buttons=max_buttons)

    def get_analogs(self, max_analogs: int = IPX_MAX_ANALOGS, **_) -> list[float | None]:
        root = self._fetch_status_root()
        return _parse_analogs_volts(root, max_analogs=max_analogs)

    def get_status(
        self,
        max_buttons: int = IPX_MAX_BUTTONS,
        max_analogs: int = IPX_MAX_ANALOGS,
    ) -> dict[str, list[float | None] | list[bool]]:
        """
        For parts of your app that expect a combined payload.
        Returns:
          {"digital": list[bool], "analog": list[float | None]}
        """
        root = self._fetch_status_root()
        digital = _parse_digitals_bool(root, max_buttons=max_buttons)
        analog = _parse_analogs_volts(root, max_analogs=max_analogs)
        return {"digital": digital, "analog": analog}

    def get_raw_status_xml(self) -> str:
        url = f"{self.base_url}{self.status_path}"
        auth = (self.user, self.password) if (self.user and self.password) else None
        r = requests.get(url, auth=auth, timeout=self.timeout, verify=self.verify_tls)
        r.raise_for_status()
        return r.text

    # ---- Internal ----

    def _fetch_status_root(self) -> ET.Element:
        xml_text = self.get_raw_status_xml()
        # guard against empty/whitespace-only responses
        if not xml_text or not xml_text.strip():
            raise ValueError("Empty response from IPX status.xml")
        return _safe_parse_xml(xml_text)


# ---------------------------
# Debug helper
# ---------------------------


def debug_extract_tags(
    xml_text: str, max_buttons: int = IPX_MAX_BUTTONS, max_analogs: int = IPX_MAX_ANALOGS
) -> dict[str, list[str]]:
    """
    Quick visibility on which tags exist in the provided XML.
    Now also reports analog{n} tags.
    """
    root = _safe_parse_xml(xml_text)

    present_btn_0 = [f"btn{i}" for i in range(max_buttons) if _element_text(root, f"btn{i}") is not None]
    present_btn_1 = [f"btn{i}" for i in range(1, max_buttons + 1) if _element_text(root, f"btn{i}") is not None]

    present_ana_0 = []
    for i in range(max_analogs):
        for nm in (f"an{i}", f"ana{i}", f"analog{i}"):
            if _element_text(root, nm) is not None:
                present_ana_0.append(nm)

    present_ana_1 = []
    for i in range(1, max_analogs + 1):
        for nm in (f"an{i}", f"ana{i}", f"analog{i}"):
            if _element_text(root, nm) is not None:
                present_ana_1.append(nm)

    return {
        "btn_zero_based": present_btn_0,
        "btn_one_based": present_btn_1,
        "analog_zero_based": present_ana_0,
        "analog_one_based": present_ana_1,
    }
