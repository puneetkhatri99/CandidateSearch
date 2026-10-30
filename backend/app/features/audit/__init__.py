"""Append-only audit trail of staff actions."""

from app.features.audit.service import AuditAction, record_event

__all__ = ["AuditAction", "record_event"]
