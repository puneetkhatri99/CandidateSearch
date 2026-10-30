import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, model_validator

from app.features.auth.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.shared.validation import StrictModel, custom_error, text

Role = Literal["admin", "recruiter"]
MAX_PAGE_SIZE = 100

Password = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class _PasswordModel(StrictModel):
    # Passwords are kept exactly as typed; stripping would change what the user must enter.
    model_config = ConfigDict(str_strip_whitespace=False)


class ChangePasswordRequest(_PasswordModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: Password


class CreateUserRequest(_PasswordModel):
    email: EmailStr
    full_name: Annotated[str, text(2, 120)]
    role: Role = "recruiter"
    temporary_password: Password


class UpdateUserRequest(StrictModel):
    role: Role | None = None
    is_active: StrictBool | None = None

    @model_validator(mode="after")
    def _at_least_one_change(self) -> Self:
        if self.role is None and self.is_active is None:
            raise custom_error("empty_update", "Provide a role or an active flag.")
        return self


class ResetPasswordRequest(_PasswordModel):
    temporary_password: Password


class UserListParams(StrictModel):
    cursor: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=50, ge=1, le=MAX_PAGE_SIZE)


class StaffUser(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    must_change_password: bool


class UserAccount(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime


class UserAccountPage(BaseModel):
    items: list[UserAccount]
    next_cursor: str | None


@dataclass(frozen=True)
class AuthContext:
    """The signed-in staff member making a request; services use it for permissions and audit."""

    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    ip: str | None
    must_change_password: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def to_staff_user(self) -> StaffUser:
        return StaffUser(
            id=self.user_id,
            email=self.email,
            full_name=self.full_name,
            role=self.role,
            must_change_password=self.must_change_password,
        )
