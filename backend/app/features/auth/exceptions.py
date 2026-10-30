from fastapi import status

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError


class InvalidCredentialsError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_credentials"

    def __init__(self) -> None:
        # Same message for unknown email, wrong password and inactive account.
        super().__init__("Invalid email or password.")


class CsrfCheckFailedError(ForbiddenError):
    code = "csrf_failed"


class PasswordChangeRequiredError(ForbiddenError):
    code = "password_change_required"

    def __init__(self) -> None:
        super().__init__("Change your password to continue.")


class InvalidCurrentPasswordError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_current_password"

    def __init__(self) -> None:
        super().__init__("Your current password is incorrect.")


class PasswordUnchangedError(AppError):
    """Shaped like FastAPI's own 422 so the SPA maps it onto the new-password field."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "validation_error"

    def __init__(self) -> None:
        message = "Choose a password different from the current one"
        super().__init__(
            "Request validation failed.",
            {
                "errors": [
                    {"loc": ["body", "new_password"], "msg": message, "type": "same_password"}
                ]
            },
        )


class UserNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("User not found.")


class UserAlreadyExistsError(ConflictError):
    code = "user_exists"


class CannotModifySelfError(ConflictError):
    code = "cannot_modify_self"


class LastAdminError(ConflictError):
    code = "last_admin"


class WeakPasswordError(AppError):
    code = "weak_password"
