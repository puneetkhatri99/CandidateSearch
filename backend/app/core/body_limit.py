"""Request body size limit, enforced as ASGI middleware.

It has to run before FastAPI reads the body: a route dependency runs only after the whole
body is buffered and parsed, so it can't protect memory or stop oversized malformed JSON.
"""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PAYLOAD_TOO_LARGE = 413


def _too_large_message(max_bytes: int) -> str:
    return f"Request body must be at most {max_bytes} bytes."


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            response = JSONResponse(
                status_code=PAYLOAD_TOO_LARGE,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": _too_large_message(self.max_bytes),
                        "details": {},
                    }
                },
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            # Chunked uploads have no Content-Length; count bytes as they arrive.
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # An HTTPException survives FastAPI's body parsing (other errors become 400)
                    # and is rendered by the standard error handler.
                    raise HTTPException(PAYLOAD_TOO_LARGE, _too_large_message(self.max_bytes))
            return message

        await self.app(scope, limited_receive, send)
