from fastapi import status

from app.core.errors import AppError


class BudgetExceededError(AppError):
    """The call would push lifetime spending over the limit, so it was not sent."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "budget_exceeded"
