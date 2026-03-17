# app/config.py
from __future__ import annotations

import os
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

    # ---- Spotify ----
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "/spotify/callback"
    spotify_token_cache_path: str = "app/data/.spotify_cache"
    spotify_speaker_device: str = "default"
    spotify_speaker_name: str = "HomeHub Speaker"

    # ---- Voice / Audio ----
    voice_enabled: bool = False
    voice_language: str = "fr"
    mic_device: str | None = None
    mic_sample_rate: int = 16000
    mic_channels: int = 1

    # ---- LLM / MCP ----
    llm_provider: str = "disabled"
    llm_model: str = "mistral"
    llm_base_url: str = "http://localhost:11434"
    llm_timeout: float = 30.0
    llm_system_prompt: str = "Tu es un assistant domotique francophone local."

    # ---- MQTT ----
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_pass: str = ""
    mqtt_client_id: str = "homehub"
    mqtt_auto_failover: bool = False  # If True, app checks for an existing broker before connecting
    shelly_debug_port: int = 1883

    # ---- Auth ----
    app_password: str | None = None
    device_verification_code: str = "1234"

    # ---- Cloudflare ----
    cloudflare_tunnel_token: str | None = None

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
    # spotify
    "SPOTIFY_CLIENT_ID": "spotify_client_id",
    "SPOTIFY_CLIENT_SECRET": "spotify_client_secret",
    "SPOTIFY_REDIRECT_URI": "spotify_redirect_uri",
    "SPOTIFY_TOKEN_CACHE_PATH": "spotify_token_cache_path",
    "SPOTIFY_SPEAKER_DEVICE": "spotify_speaker_device",
    "SPOTIFY_SPEAKER_NAME": "spotify_speaker_name",
    # voice
    "VOICE_ENABLED": "voice_enabled",
    "VOICE_LANGUAGE": "voice_language",
    "MIC_DEVICE": "mic_device",
    "MIC_SAMPLE_RATE": "mic_sample_rate",
    "MIC_CHANNELS": "mic_channels",
    # llm
    "LLM_PROVIDER": "llm_provider",
    "LLM_MODEL": "llm_model",
    "LLM_BASE_URL": "llm_base_url",
    "LLM_TIMEOUT": "llm_timeout",
    "LLM_SYSTEM_PROMPT": "llm_system_prompt",
    # mqtt
    "MQTT_HOST": "mqtt_host",
    "MQTT_PORT": "mqtt_port",
    "MQTT_USER": "mqtt_user",
    "MQTT_PASS": "mqtt_pass",
    "MQTT_CLIENT_ID": "mqtt_client_id",
    "MQTT_AUTO_FAILOVER": "mqtt_auto_failover",
    "SHELLY_DEBUG_PORT": "shelly_debug_port",
    # auth
    "APP_PASSWORD": "app_password",
    "DEVICE_VERIFICATION_CODE": "device_verification_code",
    "CLOUDFLARE_TUNNEL_TOKEN": "cloudflare_tunnel_token",
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
    # Load existing .env to preserve comments and unknown keys
    env_content = {}
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

    # Map existing keys to their line index
    key_to_line = {}
    for i, line in enumerate(lines):
        clean = line.strip()
        if clean and not clean.startswith("#") and "=" in clean:
            key = clean.split("=", 1)[0].strip()
            key_to_line[key] = i

    # Update or append known keys
    for env_key, attr in _ENV_MAP.items():
        val = getattr(s, attr, None)
        new_line = f"{env_key}={_coerce_env_value(val)}\n"
        if env_key in key_to_line:
            lines[key_to_line[env_key]] = new_line
        else:
            lines.append(new_line)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
