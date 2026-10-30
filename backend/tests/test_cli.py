import io

import pytest

from app.cli import _read_password


@pytest.mark.parametrize(
    "line",
    ["s3cret-password-x\n", "s3cret-password-x\r\n", "s3cret-password-x", "﻿s3cret-password-x\r\n"],
)
def test_stdin_password_strips_line_endings_and_bom(
    monkeypatch: pytest.MonkeyPatch, line: str
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(line))

    assert _read_password(from_stdin=True) == "s3cret-password-x"
