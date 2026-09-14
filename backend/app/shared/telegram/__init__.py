"""Telegram delivery helpers (backend-side secrets only)."""

from app.shared.telegram.client import send_message
from app.shared.telegram.delivery import queue_reset_code_delivery

__all__ = ["queue_reset_code_delivery", "send_message"]
