from asyncio import Queue
from typing import Any
from microdot import Request
from microdot.websocket import WebSocket

class PubSub:
    max_queue_size: int
    def __init__(self) -> None:
        ...

    def subscribe(self, channel: str) -> Queue[Any]:
        ...

    def unsubscribe(self, channel: str, queue: Queue[Any]) -> None:
        ...

    async def publish(self, channel: str, message: Any) -> int:
        ...

    def channels(self) -> list[str]:
        ...

    def subscriber_count(self, channel: str) -> int:
        ...

    def sse_response(self, request: Request, channels: str | list[str], event_map: dict[str, str] | None = ...):
        ...

    async def websocket_handler(self, ws: WebSocket, channels: str | list[str]) -> None:
        ...
