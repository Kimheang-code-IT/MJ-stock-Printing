"""Legacy payment-notify shim. Superseded by app.shared.telegram.service.

`queue_payment_invoice_notify` remains a no-op so any stale import keeps
working without sending anything. The canonical notification path is
`app.shared.telegram.service` (notify_sale / notify_purchase /
notify_payment_text / send_daily_summary / send_test_notification).
"""

import logging

logger = logging.getLogger("stock_pos.telegram")


def queue_payment_invoice_notify(payload: dict) -> bool:
    """No-op. Notifications go through app.shared.telegram.service only."""
    logger.debug("Legacy payment notify shim called (no-op); use shared.telegram.service")
    return False
