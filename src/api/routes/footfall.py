"""
Footfall stats endpoint — current counts from in-memory counter.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.deps import app_state
from src.api.schemas import FootfallStatsResponse

router = APIRouter()


@router.get("/footfall/current", response_model=FootfallStatsResponse)
async def get_current_footfall():
    stats = app_state.footfall_counter.stats
    return FootfallStatsResponse(
        total_entries=stats.total_entries,
        total_exits=stats.total_exits,
        current_in_store=stats.current_in_store,
        employees_filtered=stats.employees_filtered,
    )
