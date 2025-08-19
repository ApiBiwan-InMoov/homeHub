# app/ipx800/client.py
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional, Dict

import requests
from requests.auth import HTTPBasicAuth


class IPX800Client:
    """
    Minimal IPX800 v3 HTTP client.

    Assumptions (common on v3):
      - Outputs (relays) are exposed in /status.xml as <led0..led31> with "0"/"1".
        Mapping: Relay #1 -> <led0>, Relay #2 -> <led1>, ...
      - Digital inputs (buttons) as <btn0..> with "up"/"down" (or 0/1).
      - Analog inputs as <an1..> (1-based) or sometimes <an0..> (0-based).

    Methods:
      set_relay(relay:int, on:bool) -> bool
      toggle_relay(relay:int) -> bool
      get_outputs(max_relays:int=32) -> List[bool]
      read_relay(relay:int) -> bool
      get_inputs(max_buttons:int=32, max_analogs:int=16) -> dict
    """

    def __init__(
        self,
        host: str,
        port: int = 80,
        username: str = "",
        password: str = "",
        api_key: str = "",
        *,
        timeout: float = 2.0,
    ):
        self.base = f"http://{host}:{port}"
        self.auth = HTTPBasicAuth(username, password) if (username or password) else None
        self.api_key = api_key or ""
        self.timeout = timeout
        self.session = requests.Session()

    # -----------------------------
    # HTTP helpers
    # -----------------------------
    def _get(self, path: str) -> Optional[requests.Response]:
        """GET with short timeout; returns None on any error."""
        try:
            r = self.session.get(f"{self.base}{path}", auth=self.auth, timeout=self.timeout)
            if not r.ok:
                return None
            return r
        except Exception:
            return None

    def _read_xml_status(self) -> Optional[ET.Element]:
        """Return root of /status.xml or None on failure."""
        r = self._get("/status.xml")
        if r is None:
            return None
        try:
            return ET.fromstring(r.text)
        except Exception:
            return None

    # -----------------------------
    # Relay control
    # -----------------------------
    def set_relay(self, relay: int, on: bool) -> bool:
        """
        Control a relay via /preset.htm?setR{n}=0/1
        :param relay: 1-based relay number
        """
        value = 1 if on else 0
        path = f"/preset.htm?setR{relay}={value}"
        r = self._get(path)
        return bool(r)

    def toggle_relay(self, relay: int) -> bool:
        """Toggle a relay based on its current state."""
        current = self.read_relay(relay)
        return self.set_relay(relay, not current)

    # -----------------------------
    # Outputs (relays)
    # -----------------------------
    def get_outputs(self, max_relays: int = 32) -> List[bool]:
        """
        Read current output states.
        Primary source: /status.xml with <led0..> where "1"=ON.
        Fallback tags per relay are also checked: <R{n}>, <OUT{n}>, <Relay{n}>.
        """
        root = self._read_xml_status()
        if root is None:
            return [False] * max_relays

        out: List[bool] = []
        for relay in range(1, max_relays + 1):
            idx0 = relay - 1
            txt: Optional[str] = None

            # Preferred: ledN (0-based)
            el = root.find(f"led{idx0}")
            if el is not None and el.text is not None:
                txt = el.text.strip()
            else:
                # Fallbacks (less common on v3)
                for tag in (f"R{relay}", f"OUT{relay}", f"Relay{relay}"):
                    alt = root.find(tag)
                    if alt is not None and alt.text is not None:
                        txt = alt.text.strip()
                        break

            on = str(txt).lower() in ("1", "true", "on")
            out.append(on)
        return out

    def read_relay(self, relay: int) -> bool:
        states = self.get_outputs(max_relays=max(relay, 32))
        i = relay - 1
        return states[i] if 0 <= i < len(states) else False

    # -----------------------------
    # Inputs (digital + analog)
    # -----------------------------
    def get_inputs(self, max_buttons: int = 32, max_analogs: int = 16) -> Dict[str, list]:
        """
        Returns a dict with:
          {
            "digital": [bool]*max_buttons,  # True when pressed/down
            "analog":  [float|None]*max_analogs
          }

        Digital inputs: <btn0..> values "up"/"down" (or 0/1, on/off, true/false).
        Analog inputs: tries <an1..anN> (1-based). If none found, tries <an0..an(N-1)> (0-based).
        """
        root = self._read_xml_status()
        if root is None:
            return {"digital": [False] * max_buttons, "analog": [None] * max_analogs}

        # --- Digital (btn0..btnN-1) ---
        digital: List[bool] = []
        for idx0 in range(max_buttons):
            el = root.find(f"btn{idx0}")
            txt = (el.text.strip().lower() if (el is not None and el.text) else "up")
            digital.append(txt in ("down", "1", "on", "pressed", "true"))

        # --- Analog ---
        analog: List[Optional[float]] = [None] * max_analogs

        # First try 1-based an1..anN (common)
        found = False
        for i in range(1, max_analogs + 1):
            el = root.find(f"an{i}")
            if el is None or not el.text:
                continue
            s = el.text.strip().replace(",", ".")
            try:
                analog[i - 1] = float(s)
                found = True
            except ValueError:
                analog[i - 1] = None

        # If none found, try 0-based an0..an(N-1)
        if not found:
            for i in range(max_analogs):
                el = root.find(f"an{i}")
                if el is None or not el.text:
                    continue
                s = el.text.strip().replace(",", ".")
                try:
                    analog[i] = float(s)
                except ValueError:
                    analog[i] = None

        return {"digital": digital, "analog": analog}

