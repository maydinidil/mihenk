"""The release check: in --smoke mode the screens call this once they reach the server."""

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class SmokeSignal:
    def __init__(self) -> None:
        self.event = threading.Event()


class SmokeAck(BaseModel):
    received: bool


def make_router(signal: SmokeSignal | None) -> APIRouter:
    router = APIRouter()

    @router.post("/smoke/ok", response_model=SmokeAck)
    def smoke_ok() -> SmokeAck:
        if signal is None:
            raise HTTPException(status_code=404, detail="not in smoke mode")
        signal.event.set()
        return SmokeAck(received=True)

    return router
