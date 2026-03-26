"""
MJPEG video feed endpoint.

Streams annotated frames from a camera pipeline as a multipart MJPEG
response that can be displayed in an <img> tag in the browser.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import cv2
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.api.deps import app_state

router = APIRouter()


async def _mjpeg_generator(camera_id: str) -> AsyncGenerator[bytes, None]:
    pipeline = app_state.pipelines.get(camera_id)
    if pipeline is None:
        return

    while True:
        frame = pipeline.get_annotated_frame()
        if frame is not None:
            _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
            )

        await asyncio.sleep(0.066)


@router.get("/cameras/{camera_id}/feed")
async def camera_feed(camera_id: str):
    """Stream annotated video as MJPEG."""
    if camera_id not in app_state.pipelines:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    return StreamingResponse(
        _mjpeg_generator(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
