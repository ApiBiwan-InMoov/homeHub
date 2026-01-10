# app/config.py
from __future__ import annotations

from typing import Any

# Pydantic v2 uses pydantic-settings; fall back if not installed.
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore

    _HAS_SETTINGS_V2 = True
except Exception:
    from pydantic import BaseSettings  # type: ignore

    SettingsConfigDict = None  # type: ignore
    _HAS_SETTINGS_V2 = False


class Settings(BaseSettings):
    # ---- App/server ----
    host: str = "0.0.0.0"
    port: int = 8080
    timezone: str = "Europe/Brussels"

    # ---- Location (used by travel + weather) ----
    latitude: float = 50.716
    longitude: float = 4.519

    # ---- Poller ----
    poll_every_seconds: float = 2.0

    # ---- IPX ----
    ipx_host: str = ""
    ipx_port: int = 80
    ipx_user: str = ""
    ipx_pass: str = ""
    ipx_lights_relay: int = 1
    ipx_heating_relay: int = 2
    ipx_poll_interval: float = 2.0

    # Allow overriding the concrete client class via .env
    ipx_client_module: str | None = None  # e.g. "app.ipx800.client"
    ipx_client_class: str | None = None  # e.g. "IPX800Client"

    # ---- Google Calendar ----
    google_calendar_id: str = ""
    google_oauth_client_secrets: str = "secrets/client_secret.json"
    google_token_file: str = "secrets/token.json"
    google_oauth_redirect_uri: str | None = None
    calendar_prefs_path: str = "app/data/calendars.json"

    # ---- Google Maps ----
    google_maps_api_key: str | None = None

    # Pydantic v2 configuration
    if _HAS_SETTINGS_V2 and SettingsConfigDict is not None:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )
    else:
        # Fallback for environments without pydantic-settings (or v1 style)
        class Config:  # type: ignore[no-redef]
            env_file = ".env"
            env_file_encoding = "utf-8"


# Singleton settings object
settings = Settings()


# --- Persist selected settings back to .env (simple writer) -------------------
_ENV_MAP: dict[str, str] = {
    # server
    "HOST": "host",
    "PORT": "port",
    "TIMEZONE": "timezone",
    # location
    "LATITUDE": "latitude",
    "LONGITUDE": "longitude",
    # poller
    "POLL_EVERY_SECONDS": "poll_every_seconds",
    # ipx
    "IPX_HOST": "ipx_host",
    "IPX_PORT": "ipx_port",
    "IPX_USER": "ipx_user",
    "IPX_PASS": "ipx_pass",
    "IPX_LIGHTS_RELAY": "ipx_lights_relay",
    "IPX_HEATING_RELAY": "ipx_heating_relay",
    "IPX_POLL_INTERVAL": "ipx_poll_interval",
    "IPX_CLIENT_MODULE": "ipx_client_module",
    "IPX_CLIENT_CLASS": "ipx_client_class",
    # google
    "GOOGLE_CALENDAR_ID": "google_calendar_id",
    "GOOGLE_OAUTH_CLIENT_SECRETS": "google_oauth_client_secrets",
    "GOOGLE_TOKEN_FILE": "google_token_file",
    "GOOGLE_OAUTH_REDIRECT_URI": "google_oauth_redirect_uri",
    "CALENDAR_PREFS_PATH": "calendar_prefs_path",
    "GOOGLE_MAPS_API_KEY": "google_maps_api_key",
}


def _coerce_env_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def save_settings(s: Settings, path: str = ".env") -> None:
    """
    Minimal .env writer: writes only the known keys from _ENV_MAP.
    This overwrites the file; extend if you need to preserve unknown lines.
    """
    lines = []
    for env_key, attr in _ENV_MAP.items():
        val = getattr(s, attr, None)
        lines.append(f"{env_key}={_coerce_env_value(val)}")
    content = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
