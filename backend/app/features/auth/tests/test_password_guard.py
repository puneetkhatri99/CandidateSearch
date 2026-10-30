import uuid
from typing import get_args

import pytest

from app.features.auth.dependencies import (
    SessionUser,
    get_auth_context,
    get_session_context,
)
from app.features.auth.exceptions import PasswordChangeRequiredError
from app.features.auth.schemas import AuthContext


def _context(*, must_change_password: bool) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4(),
        email="staff@example.com",
        full_name="Staff Member",
        role="recruiter",
        ip=None,
        must_change_password=must_change_password,
    )


async def test_a_flagged_user_is_refused_by_the_default_dependency() -> None:
    with pytest.raises(PasswordChangeRequiredError) as caught:
        await get_auth_context(_context(must_change_password=True))

    assert caught.value.code == "password_change_required"
    assert caught.value.status_code == 403


async def test_an_unflagged_user_passes_through() -> None:
    context = _context(must_change_password=False)

    assert await get_auth_context(context) is context


def test_session_user_skips_the_password_guard() -> None:
    dependency = get_args(SessionUser)[1].dependency
    assert dependency is get_session_context


def test_the_staff_user_view_carries_the_flag() -> None:
    assert _context(must_change_password=True).to_staff_user().must_change_password is True
