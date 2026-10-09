"""Notification routes: send a test message through one channel."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from trdex.api.app import verify_api_key

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


class TestRequest(BaseModel):
    channel: Literal["telegram", "email"]


@router.post("/test")
async def send_test(body: TestRequest, _key: str = Depends(verify_api_key)) -> dict[str, str]:
    """Send a test message via ``channel``, ignoring the per-event routes.

    ``result`` is ``sent``, ``not configured`` or ``error: ...``.
    """
    from trdex.notify.service import Notifier

    result = await Notifier().send_via(
        body.channel,
        "trdex test notification",
        "If you can read this, the channel works.",
    )
    return {"channel": body.channel, "result": result}
