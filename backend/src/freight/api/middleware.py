"""Bound request memory before JSON parsing; log metadata without query strings."""

import asyncio
import json
import logging
from time import perf_counter
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from freight.settings import get_settings

logger = logging.getLogger("uvicorn.error.freight.requests")


class RequestBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status = 500

        async def tracked_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        async def reject(code: int, detail: str) -> None:
            await JSONResponse({"detail": detail}, status_code=code)(scope, receive, tracked_send)

        try:
            if scope["method"] in ("POST", "PUT", "PATCH", "DELETE"):
                limit = get_settings().max_request_bytes
                headers = dict(scope["headers"])
                try:
                    declared = int(headers.get(b"content-length", b"0"))
                except ValueError:
                    await reject(400, "Invalid Content-Length")
                    return
                if declared < 0 or declared > limit:
                    await reject(413, "Request body is too large")
                    return
                chunks: list[bytes] = []
                total = 0
                try:
                    async with asyncio.timeout(15):
                        while True:
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                return
                            chunk = message.get("body", b"")
                            total += len(chunk)
                            if total > limit:
                                await reject(413, "Request body is too large")
                                return
                            chunks.append(chunk)
                            if not message.get("more_body", False):
                                break
                except TimeoutError:
                    await reject(408, "Request body timed out")
                    return
                body = b"".join(chunks)
                delivered = False

                async def replay() -> Message:
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()

                await self.app(scope, replay, tracked_send)
            else:
                await self.app(scope, receive, tracked_send)
        finally:
            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "elapsed_ms": round((perf_counter() - started) * 1000),
                    }
                )
            )
