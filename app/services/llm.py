from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import requests


class LLMError(Exception):
    """Base error for LLM operations."""


class LLMNotConfigured(LLMError):
    """Raised when the provider is disabled or missing."""


class LLMUnavailable(LLMError):
    """Raised when the provider cannot be reached or returns an error."""


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str
    timeout: float = 30.0
    system_prompt: str | None = None


class LLMClient:
    def __init__(self, cfg: LLMConfig) -> None:
        self.provider = (cfg.provider or "").strip().lower() or "disabled"
        self.model = cfg.model
        self.base_url = cfg.base_url.rstrip("/")
        self.timeout = cfg.timeout
        self.system_prompt = cfg.system_prompt

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────
    def _enabled(self) -> bool:
        return self.provider not in {"", "disabled", "none"}

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────
    def info(self, check: bool = False) -> dict[str, Any]:
        info: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "configured": self._enabled(),
        }
        if not info["configured"]:
            info["status"] = "disabled"
            return info

        if self.provider == "mock":
            info["status"] = "ok"
            info["mock"] = True
            return info

        if check:
            try:
                health = self.health()
                info.update({"status": "ok", "health": health})
            except LLMError as e:
                info.update({"status": "unreachable", "error": str(e)})
        else:
            info["status"] = "configured"
        return info

    def health(self) -> dict[str, Any]:
        if not self._enabled():
            raise LLMNotConfigured("LLM provider is disabled")

        if self.provider == "mock":
            return {"ok": True, "provider": "mock"}

        if self.provider == "ollama":
            url = f"{self.base_url}/api/tags"
            try:
                r = requests.get(url, timeout=self.timeout)
            except Exception as e:  # pragma: no cover - network failure path
                raise LLMUnavailable(f"Ollama unreachable: {e}") from e
            if r.status_code >= 400:
                raise LLMUnavailable(f"Ollama tags endpoint HTTP {r.status_code}")
            try:
                data = r.json()
            except Exception as e:  # pragma: no cover - malformed JSON
                raise LLMUnavailable(f"Invalid response from Ollama: {e}") from e
            models = []
            if isinstance(data, dict):
                models = [m.get("name") for m in data.get("models", []) if isinstance(m, dict) and m.get("name")]
            info: dict[str, Any] = {"ok": True, "models": models}
            if self.model and models and self.model not in models:
                info["warning"] = f"Model '{self.model}' not found on Ollama host"
            return info

        raise LLMUnavailable(f"Unknown provider '{self.provider}'")

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> dict[str, Any]:
        if not prompt or not str(prompt).strip():
            raise ValueError("prompt is required")
        if not self._enabled():
            raise LLMNotConfigured("LLM provider is disabled")

        if self.provider == "mock":
            return {
                "text": f"[mock] Réponse simulée (fr): {str(prompt).strip()[:120]}",
                "provider": "mock",
                "model": "mock",
            }

        if self.provider == "ollama":
            url = f"{self.base_url}/api/generate"
            payload: Dict[str, Any] = {
                "model": self.model,
                "prompt": prompt,
                "system": system or self.system_prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max(1, int(max_tokens or 1)),
                },
            }
            try:
                r = requests.post(url, json=payload, timeout=self.timeout)
            except Exception as e:  # pragma: no cover - network failure path
                raise LLMUnavailable(f"Ollama unreachable: {e}") from e
            if r.status_code >= 400:
                raise LLMUnavailable(f"Ollama HTTP {r.status_code}: {r.text}")
            try:
                data = r.json()
            except Exception as e:  # pragma: no cover - malformed JSON
                raise LLMUnavailable(f"Invalid response from Ollama: {e}") from e
            if isinstance(data, dict) and data.get("error"):
                raise LLMUnavailable(str(data.get("error")))
            text = ""
            if isinstance(data, dict):
                text = data.get("response") or ""
            return {"text": text, "provider": "ollama", "model": self.model, "raw": data}

        raise LLMUnavailable(f"Unsupported provider '{self.provider}'")
