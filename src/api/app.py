"""
FastAPI application factory.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import cameras, config, footfall, video_feed


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="RetailVision API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(video_feed.router, prefix="/api/v1", tags=["video"])
    app.include_router(cameras.router, prefix="/api/v1", tags=["cameras"])
    app.include_router(config.router, prefix="/api/v1", tags=["config"])
    app.include_router(footfall.router, prefix="/api/v1", tags=["footfall"])

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        """Plain JSON so browsers always get a valid HTTP body (no redirect edge cases)."""
        return {
            "service": "RetailVision",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "cameras": "/api/v1/cameras",
            "feed": "/api/v1/cameras/{camera_id}/feed",
            "footfall": "/api/v1/footfall/current",
            "config": "/api/v1/config",
        }

    return app
