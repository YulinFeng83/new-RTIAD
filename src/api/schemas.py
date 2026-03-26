"""
Pydantic request/response schemas for the REST API.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ZoneCreateRequest(BaseModel):
    id: str
    type: str = "bidirectional"
    polygon: list[list[int]]
    direction: list[float] = Field(default_factory=lambda: [0.0, -1.0])
    name: str = ""


class ZoneResponse(BaseModel):
    id: str
    camera_id: str
    type: str
    polygon: list[list[int]]
    direction: list[float]
    name: str


class CameraResponse(BaseModel):
    id: str
    url: str
    scene_type: str
    zones: list[ZoneResponse]


class FootfallStatsResponse(BaseModel):
    total_entries: int
    total_exits: int
    current_in_store: int
    employees_filtered: int


class ConfigUpdateRequest(BaseModel):
    """Accepts partial or full config updates as a raw dict."""
    config: dict
