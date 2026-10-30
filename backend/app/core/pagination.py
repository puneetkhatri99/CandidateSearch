"""Opaque cursors for keyset pagination.

A cursor is base64url JSON. Clients must treat it as opaque; the server validates its shape
on decode so a tampered cursor gives a 400, not a 500.
"""

import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from fastapi import status

from app.core.errors import AppError


class InvalidCursorError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_cursor"


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError("The page cursor is invalid. Start the search again.") from exc
    if not isinstance(payload, dict):
        raise InvalidCursorError("The page cursor is invalid. Start the search again.")
    return payload


def parse_cursor_position(created_at: object, row_id: object) -> tuple[datetime, uuid.UUID]:
    """Turn a decoded (created_at, id) cursor back into typed values Postgres can store.

    Values decoded from a cursor bypass Pydantic, so a naive or out-of-range timestamp would
    otherwise fail inside the driver as a 500. Raises ValueError on anything unusable.
    """
    if not isinstance(created_at, str) or not isinstance(row_id, str):
        raise ValueError("cursor fields must be strings")
    parsed = datetime.fromisoformat(created_at)
    if parsed.tzinfo is None or not 2000 <= parsed.year <= 3000:
        raise ValueError("cursor timestamp out of range")
    return parsed, uuid.UUID(row_id)


class _Row(Protocol):
    @property
    def id(self) -> uuid.UUID: ...
    @property
    def created_at(self) -> datetime: ...


def decode_created_at_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    """The (created_at, id) position a newest-first list continues after, or None for page 1."""
    if not cursor:
        return None
    payload = decode_cursor(cursor)
    try:
        return parse_cursor_position(payload["key"], payload["id"])
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise InvalidCursorError("The page cursor is invalid. Start again.") from exc


def next_created_at_cursor[T: _Row](
    rows: Sequence[T], limit: int
) -> tuple[Sequence[T], str | None]:
    """Split `limit + 1` fetched rows into the page and the cursor for the next one."""
    page = rows[:limit]
    if len(rows) <= limit or not page:
        return page, None
    last = page[-1]
    return page, encode_cursor({"key": last.created_at.isoformat(), "id": str(last.id)})
