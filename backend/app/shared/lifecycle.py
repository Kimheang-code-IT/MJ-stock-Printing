"""Shared lifecycle helpers for ACTIVE / INACTIVE (or DISABLED) records."""

from __future__ import annotations

from app.core.exceptions import ConflictError

_ACTIVE_STATUSES = frozenset({"ACTIVE", ""})


def assert_inactive_for_delete(status: str | None, *, label: str = "record") -> None:
    """Refuse hard-delete while the record is still active.

    Roles use DISABLED for the inactive state; every other status-bearing
    master-data table uses INACTIVE. Empty/missing status is treated as active.
    """
    value = str(status or "").strip().upper()
    if value in _ACTIVE_STATUSES:
        raise ConflictError(
            f"Cannot delete an active {label}. Deactivate it first."
        )
