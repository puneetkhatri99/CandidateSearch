import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.errors import AppError
from app.core.pagination import (
    InvalidCursorError,
    decode_created_at_cursor,
    decode_cursor,
    encode_cursor,
    next_created_at_cursor,
    parse_cursor_position,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
ROW_ID = uuid.uuid4()


def test_cursor_round_trips() -> None:
    payload = {"sort": "name", "key": "asha verma", "id": "1234"}

    assert decode_cursor(encode_cursor(payload)) == payload


@pytest.mark.parametrize("cursor", ["%%%", "bm90LWpzb24", "WzEsMl0"])  # junk, non-JSON, a list
def test_tampered_cursor_raises(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)


def test_a_valid_position_parses() -> None:
    assert parse_cursor_position(NOW.isoformat(), str(ROW_ID)) == (NOW, ROW_ID)


@pytest.mark.parametrize(
    ("created_at", "row_id"),
    [
        ("2026-10-29T12:00:00", str(ROW_ID)),  # naive datetime
        ("0001-01-01T00:00:00+00:00", str(ROW_ID)),  # year out of range
        ("9999-01-01T00:00:00+00:00", str(ROW_ID)),
        ("not a date", str(ROW_ID)),
        (NOW.isoformat(), "not-a-uuid"),
        (NOW.isoformat(), str(ROW_ID) + "\x00"),
        (123, str(ROW_ID)),
        (NOW.isoformat(), None),
        (None, None),
    ],
)
def test_unusable_positions_raise_value_error(created_at: Any, row_id: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_cursor_position(created_at, row_id)


@pytest.mark.parametrize(
    "payload",
    [
        {"key": "2026-10-29T12:00:00", "id": str(ROW_ID)},
        {"key": NOW.isoformat()},
        {"id": str(ROW_ID)},
        {"key": ["x"], "id": {"y": 1}},
        {"key": "x" * 400, "id": str(ROW_ID)},
    ],
)
def test_bad_created_at_cursors_are_invalid_cursor(payload: dict[str, Any]) -> None:
    with pytest.raises(InvalidCursorError):
        decode_created_at_cursor(encode_cursor(payload))


@pytest.mark.parametrize("cursor", ["!!!", "bnVsbA", "WzFd"])  # not base64, `null`, `[1]`
def test_malformed_or_non_dict_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(AppError) as caught:
        decode_created_at_cursor(cursor)
    assert caught.value.code == "invalid_cursor"


def test_no_cursor_means_the_first_page() -> None:
    assert decode_created_at_cursor(None) is None


@dataclass
class _Row:
    id: uuid.UUID
    created_at: datetime


def test_next_cursor_points_after_the_last_row_only_when_more_exist() -> None:
    rows = [_Row(uuid.uuid4(), NOW - timedelta(minutes=i)) for i in range(3)]

    page, cursor = next_created_at_cursor(rows, 2)
    assert page == rows[:2]
    assert cursor is not None
    assert decode_created_at_cursor(cursor) == (rows[1].created_at, rows[1].id)

    assert next_created_at_cursor(rows, 3) == (rows, None)
    assert next_created_at_cursor([], 3) == ([], None)
