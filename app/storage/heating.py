# app/storage/heating.py
from __future__ import annotations
import json
import os
from typing import Any, List, Optional
from pydantic import BaseModel, Field
from app.config import settings

DATA_DIR = "app/data"
CONFIG_PATH = os.path.join(DATA_DIR, "heating_config.json")

class DDGConfig(BaseModel):
    override_active: bool = False
    override_value: float = 0.0

class ZoneConfig(BaseModel):
    id: str
    label: str
    temp_source_type: str = "analog"  # "analog" or "shelly"
    temp_source_index: Optional[int] = None
    temp_source_prefix: Optional[str] = None
    target_temp: float = 20.0

class StatusItem(BaseModel):
    label: str
    type: str  # "ipx_relay", "ipx_input", "shelly_switch"
    index: Optional[int] = None
    prefix: Optional[str] = None

class HeatingConfig(BaseModel):
    mode: str = "winter"  # "winter" or "summer"
    ddg: DDGConfig = Field(default_factory=DDGConfig)
    zones: List[ZoneConfig] = Field(default_factory=list)
    status_summary: List[StatusItem] = Field(default_factory=list)

def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)

def load_heating_config() -> HeatingConfig:
    _ensure_dir()
    if not os.path.exists(CONFIG_PATH):
        # Default config
        config = HeatingConfig(
            mode="winter",
            ddg=DDGConfig(),
            zones=[
                ZoneConfig(id="living", label="Salon", temp_source_type="analog", temp_source_index=0, target_temp=21.0)
            ],
            status_summary=[
                StatusItem(label="Chaudière", type="ipx_relay", index=settings.ipx_heating_relay - 1 if settings.ipx_heating_relay else 0)
            ]
        )
        save_heating_config(config)
        return config
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
            return HeatingConfig(**data)
    except Exception:
        return HeatingConfig()

def save_heating_config(config: HeatingConfig) -> None:
    _ensure_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        # Pydantic v2 use model_dump, fallback to dict for v1
        if hasattr(config, "model_dump"):
            data = config.model_dump()
        else:
            data = config.dict()
        json.dump(data, f, indent=2, ensure_ascii=False)
