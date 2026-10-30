"""Staff authentication: users, server-side sessions, roles."""

from app.features.auth.admin_router import router as admin_router
from app.features.auth.dependencies import (
    AdminUser,
    CurrentUser,
    SessionUser,
    require_fetch_header_on_any_method,
    require_role,
)
from app.features.auth.router import router
from app.features.auth.schemas import AuthContext, Role, StaffUser
from app.features.auth.service import create_user, get_full_names, prune_expired_sessions

__all__ = [
    "AdminUser",
    "AuthContext",
    "CurrentUser",
    "Role",
    "SessionUser",
    "StaffUser",
    "admin_router",
    "create_user",
    "get_full_names",
    "prune_expired_sessions",
    "require_fetch_header_on_any_method",
    "require_role",
    "router",
]
