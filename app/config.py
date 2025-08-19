from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

class Settings(BaseSettings):
    """Typed application settings loaded from env/.env via pydantic-settings."""
    # IPX800
    ipx_host: str = Field(default="192.168.1.50")
    ipx_port: int = Field(default=80)
    ipx_user: str = Field(default="")
    ipx_pass: str = Field(default="")
    ipx_lights_relay: int = Field(default=1)
    ipx_heating_relay: int = Field(default=2)
    ipx_poll_interval: float = Field(default=2.0)

    # Google
    google_calendar_id: str = Field(default="")
    google_oauth_client_secrets: str = Field(default="secrets/client_secret.json")
    google_token_file: str = Field(default="secrets/token.json")

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)

    # Location
    latitude: float = Field(default=50.716)
    longitude: float = Field(default=4.519)
    timezone: str = Field(default="Europe/Brussels")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @field_validator("ipx_port", "port")
    @classmethod
    def _port_positive(cls, v: int) -> int:
        if v <= 0 or v > 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

settings = Settings()
