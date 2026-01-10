from __future__ import annotations

import json
import os
from typing import Any

from app.config import settings

VOICE_CONFIG_PATH = os.environ.get("VOICE_CONFIG_PATH", "app/data/voice_config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "device": settings.mic_device,
    "sample_rate": settings.mic_sample_rate,
    "channels": settings.mic_channels,
    # Browser-side hints (for UI only)
    "browser_device_id": None,
    "browser_label": None,
    # Browser constraints (best-effort; may be ignored by user agent)
    "echo_cancellation": True,
    "noise_suppression": True,
    "auto_gain_control": True,
}


def _ensure_dir() -> None:
    d = os.path.dirname(VOICE_CONFIG_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _merge_default(cfg: dict[str, Any] | None) -> dict[str, Any]:
    base = json.loads(json.dumps(DEFAULT_CONFIG))
    if not cfg:
        return base
    base.update({k: v for k, v in cfg.items() if v is not None or k in base})
    return base


def load_voice_config() -> dict[str, Any]:
    _ensure_dir()
    if not os.path.exists(VOICE_CONFIG_PATH):
        try:
            save_voice_config(DEFAULT_CONFIG)
        except PermissionError:
            pass
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(VOICE_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = json.loads(json.dumps(DEFAULT_CONFIG))
    return _merge_default(data)


def save_voice_config(cfg: dict[str, Any]) -> dict[str, Any]:
    _ensure_dir()
    merged = _merge_default(cfg)
    try:
        with open(VOICE_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
    except PermissionError:
        # Fallback to runtime-only config if disk is read-only
        return merged
    return merged


def list_input_devices() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    info: dict[str, Any] = {
        "diagnostic": None,
        "has_dev_snd": os.path.isdir("/dev/snd"),
    }
    if info["has_dev_snd"]:
        try:
            info["dev_snd_entries"] = sorted(os.listdir("/dev/snd"))[:10]
        except Exception:
            pass
    try:
        import sounddevice as sd
    except Exception as e:  # sounddevice missing or backend unavailable
        info["diagnostic"] = f"sounddevice not available: {e}"
        return [], info

    try:
        hostapis = sd.query_hostapis()
        info["hostapis"] = [
            {
                "index": idx,
                "name": (api.get("name") if isinstance(api, dict) else getattr(api, "name", None)) or "",
                "type": (api.get("type") if isinstance(api, dict) else getattr(api, "type", None)) or None,
                "device_count": api.get("device_count") if isinstance(api, dict) else getattr(api, "device_count", None),
            }
            for idx, api in enumerate(hostapis or [])
        ]
        try:
            info["default_hostapi"] = getattr(getattr(sd, "default", None), "hostapi", None)
        except Exception:
            pass
    except Exception as e:
        info["hostapis_error"] = str(e)

    try:
        devices = sd.query_devices()
        default_in = None
        try:
            if getattr(sd, "default", None) and getattr(sd.default, "device", None):
                default_in = sd.default.device[0]
        except Exception:
            default_in = None
    except Exception as e:
        info["diagnostic"] = f"could not query devices: {e}"
        return [], info

    out: list[dict[str, Any]] = []
    for idx, dev in enumerate(devices):
        try:
            max_in = dev.get("max_input_channels", 0) if isinstance(dev, dict) else getattr(dev, "max_input_channels", 0)
            if max_in is None:
                max_in = 0
            if max_in <= 0:
                continue
            out.append(
                {
                    "id": idx,
                    "name": dev.get("name", f"Device {idx}") if isinstance(dev, dict) else getattr(dev, "name", f"Device {idx}"),
                    "max_input_channels": max_in,
                    "default_samplerate": dev.get("default_samplerate") if isinstance(dev, dict) else getattr(dev, "default_samplerate", None),
                    "hostapi": dev.get("hostapi") if isinstance(dev, dict) else getattr(dev, "hostapi", None),
                    "is_default": (default_in == idx),
                }
            )
        except Exception:
            continue

    if not out:
        info["diagnostic"] = info.get("diagnostic") or (
            "Aucun périphérique d'entrée détecté côté serveur (ALSA/driver). "
            "Exposez /dev/snd au conteneur (ex: --device /dev/snd --group-add audio) ou vérifiez les pilotes ALSA."
        )
    return out, info