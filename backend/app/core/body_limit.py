"""Request body size limit, enforced as ASGI middleware.

It has to run before FastAPI reads the body: a route dependency runs only after the whole
body is buffered and parsed, so it can't protect memory or stop oversized malformed JSON.
"""

import re

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PAYLOAD_TOO_LARGE = 413


def _too_large_message(max_bytes: int) -> str:
    return f"Request body must be at most {max_bytes} bytes."


class BodySizeLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int,
        *,
        upload_paths: re.Pattern[str] | None = None,
        upload_max_bytes: int = 0,
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        # File uploads (matched on the full path) get their own, larger limit.
        self.upload_paths = upload_paths
        self.upload_max_bytes = upload_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_upload = self.upload_paths is not None and self.upload_paths.fullmatch(scope["path"])
        max_bytes = self.upload_max_bytes if is_upload else self.max_bytes
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            response = JSONResponse(
                status_code=PAYLOAD_TOO_LARGE,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": _too_large_message(max_bytes),
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
                if received > max_bytes:
                    # An HTTPException survives FastAPI's body parsing (other errors become 400)
                    # and is rendered by the standard error handler.
                    raise HTTPException(PAYLOAD_TOO_LARGE, _too_large_message(max_bytes))
            return message

        await self.app(scope, limited_receive, send)
