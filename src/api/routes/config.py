"""
Config endpoints — get/update the running configuration.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.deps import app_state
from src.config import AppConfig

router = APIRouter()


@router.get("/config")
async def get_config():
    return app_state.config_manager.config.model_dump(mode="json")


@router.put("/config")
async def update_config(body: dict):
    """
    Accept a full or partial config update.
    Merges with existing config and triggers hot-reload.
    """
    current = app_state.config_manager.config.model_dump(mode="json")
    _deep_merge(current, body)
    new_config = AppConfig(**current)
    app_state.config_manager.update_config(new_config)
    return {"detail": "Config updated", "config": new_config.model_dump(mode="json")}


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
