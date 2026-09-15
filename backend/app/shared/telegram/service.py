"""Canonical Telegram notification service (spec §3.6).

One service owns every business notification: expiry alerts, sale
notifications, purchase (Stock In) notifications, the daily summary and the
test message. Rules:

- Every notification type is gated by a Settings toggle
  (telegram.*_enabled) read per send — changing a toggle takes effect
  immediately.
- Delivery failures NEVER raise into business flows: callers invoke this
  module after their transaction has committed, and every send swallows and
  logs errors.
- No invoice/receipt files or PDFs are ever sent — plain text only.
- Recipients are every ACTIVE user with a verified telegram_chat_id.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.administration.service import get_setting_value
from app.modules.auth.models import User

logger = logging.getLogger("stock_pos.telegram")

Sender = callable


async def telegram_enabled(session: AsyncSession) -> bool:
    """Master switch: settings.telegram.enabled and a saved/env bot token."""
    from app.core.config import settings as app_settings
    from app.shared.telegram.client import resolve_bot_token

    if not app_settings.telegram_enabled or not await resolve_bot_token(session):
        return False
    return bool(await get_setting_value(session, "telegram", "enabled", True))


async def recipients(session: AsyncSession) -> list[str]:
    result = await session.execute(
        select(User.telegram_chat_id).where(
            User.status == "ACTIVE",
            User.telegram_verified.is_(True),
            User.telegram_chat_id.is_not(None),
            User.telegram_chat_id != "",
        )
    )
    recipient_list = [str(chat_id) for chat_id in result.scalars().all()]
    # The Settings Telegram "Chat/Group ID" is a global fallback recipient
    # (e.g. a group chat) in addition to the verified per-user chats.
    configured = str(await get_setting_value(session, "telegram", "chat_id", "") or "").strip()
    if configured and configured not in recipient_list:
        recipient_list.append(configured)
    return recipient_list


async def _broadcast(session: AsyncSession, text: str, *, sender=None) -> int:
    """Send one text to every recipient. Returns the delivered count."""
    sender = sender or _default_sender
    delivered = 0
    for chat_id in await recipients(session):
        try:
            if await sender(chat_id, text):
                delivered += 1
        except Exception:  # noqa: BLE001 — one bad recipient must not stop the broadcast
            logger.exception("Telegram send failed for chat %s", chat_id)
    return delivered


async def _default_sender(chat_id: str, text: str) -> bool:
    from app.shared.telegram.client import send_message

    return await send_message(chat_id, text)


def _local_today(session_tz: str) -> date:
    try:
        tz = ZoneInfo(session_tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


async def notify_sale(
    session: AsyncSession,
    *,
    invoice_no: str,
    occurred_at: datetime,
    customer: str | None,
    currency: str,
    exchange_rate,
    subtotal,
    discount,
    delivery_price,
    total,
    paid,
    payment_method: str,
    debt,
    cashier: str | None,
    item_count: int,
    sender=None,
) -> bool:
    """Sale notification (after commit). Never raises."""
    try:
        if not await get_setting_value(session, "telegram", "enabled", True):
            return False
        if not await get_setting_value(session, "telegram", "sale_enabled", False):
            return False
        tz_name = await get_setting_value(session, "system", "timezone", "UTC")
        text = format_sale_text(
            {
                "invoice_no": invoice_no,
                "occurred_at": occurred_at.isoformat(),
                "customer": customer,
                "currency": currency,
                "exchange_rate": str(exchange_rate),
                "subtotal": str(subtotal),
                "discount": str(discount),
                "delivery_price": str(delivery_price),
                "total": str(total),
                "paid": str(paid),
                "payment_method": payment_method,
                "debt": str(debt),
                "cashier": cashier,
                "item_count": item_count,
            },
            timezone_name=str(tz_name or "UTC"),
        )
        sent = await _broadcast(session, text, sender=sender)
        return sent > 0
    except Exception:
        logger.exception("Telegram sale notification failed for %s", invoice_no)
        return False


async def notify_purchase(
    session: AsyncSession,
    *,
    document_no: str,
    occurred_at: datetime,
    supplier: str | None,
    currency: str,
    exchange_rate,
    subtotal,
    discount,
    tax,
    total,
    paid,
    debt,
    user: str | None,
    item_count: int,
    sender=None,
) -> bool:
    """Stock In (purchase) notification (after commit). Never raises."""
    try:
        if not await get_setting_value(session, "telegram", "enabled", True):
            return False
        if not await get_setting_value(session, "telegram", "purchase_enabled", False):
            return False
        tz_name = await get_setting_value(session, "system", "timezone", "UTC")
        text = format_purchase_text(
            {
                "document_no": document_no,
                "occurred_at": occurred_at.isoformat(),
                "supplier": supplier,
                "currency": currency,
                "exchange_rate": str(exchange_rate),
                "subtotal": str(subtotal),
                "discount": str(discount),
                "tax": str(tax),
                "total": str(total),
                "paid": str(paid),
                "debt": str(debt),
                "user": user,
                "item_count": item_count,
            },
            timezone_name=str(tz_name or "UTC"),
        )
        sent = await _broadcast(session, text, sender=sender)
        return sent > 0
    except Exception:
        logger.exception("Telegram purchase notification failed for %s", document_no)
        return False


async def notify_payment_text(
    session: AsyncSession,
    *,
    invoice_no: str,
    payment_no: str,
    customer: str | None,
    total,
    paid,
    payment_method: str,
    remaining,
    cashier: str | None,
    sender=None,
) -> bool:
    """Debt-payment text notification (after commit). Never raises.

    Gated by the sale-notification toggle: debt payments are the payment
    stream of the sale, not invoice documents (no files are ever sent)."""
    try:
        if not await get_setting_value(session, "telegram", "enabled", True):
            return False
        if not await get_setting_value(session, "telegram", "sale_enabled", False):
            return False
        tz_name = await get_setting_value(session, "system", "timezone", "UTC")
        text = format_payment_text(
            {
                "invoice_no": invoice_no,
                "payment_no": payment_no,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "customer": customer,
                "total": str(total),
                "paid": str(paid),
                "payment_method": payment_method,
                "remaining": str(remaining),
                "cashier": cashier,
            },
            timezone_name=str(tz_name or "UTC"),
        )
        sent = await _broadcast(session, text, sender=sender)
        return sent > 0
    except Exception:
        logger.exception("Telegram payment notification failed for %s", invoice_no)
        return False


async def notify_supplier_payment_text(
    session: AsyncSession,
    *,
    document_no: str | None,
    payment_no: str,
    supplier: str | None,
    total,
    paid,
    payment_method: str,
    remaining,
    cashier: str | None,
    sender=None,
) -> bool:
    """Supplier debt-payment text notification (after commit). Never raises.

    Supplier debts originate from Stock In, so the purchase toggle gates it."""
    try:
        if not await get_setting_value(session, "telegram", "enabled", True):
            return False
        if not await get_setting_value(session, "telegram", "purchase_enabled", False):
            return False
        tz_name = await get_setting_value(session, "system", "timezone", "UTC")
        text = format_supplier_payment_text(
            {
                "document_no": document_no,
                "payment_no": payment_no,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "supplier": supplier,
                "total": str(total),
                "paid": str(paid),
                "payment_method": payment_method,
                "remaining": str(remaining),
                "cashier": cashier,
            },
            timezone_name=str(tz_name or "UTC"),
        )
        sent = await _broadcast(session, text, sender=sender)
        return sent > 0
    except Exception:
        logger.exception("Telegram supplier payment notification failed for %s", payment_no)
        return False


async def send_test_notification(session: AsyncSession, *, sender=None) -> dict:
    """Settings-driven connectivity test (Administration → Settings)."""
    if not await telegram_enabled(session):
        return {"enabled": False, "sent": 0, "recipients": 0}
    tz_name = await get_setting_value(session, "system", "timezone", "UTC")
    text = (
        "Stock & POS — test notification\n"
        f"Time: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"Timezone: {tz_name}\n"
        "Telegram notifications are configured correctly."
    )
    chats = await recipients(session)
    sent = await _broadcast(session, text, sender=sender)
    return {"enabled": True, "sent": sent, "recipients": len(chats)}


# ------------------------------------------------------------------ formatters


def _stamp(raw: str, timezone_name: str) -> str:
    try:
        moment = datetime.fromisoformat(str(raw))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("UTC"))
        try:
            moment = moment.astimezone(ZoneInfo(timezone_name or "UTC"))
        except (ZoneInfoNotFoundError, ValueError):
            moment = moment.astimezone(ZoneInfo("UTC"))
        return moment.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    except ValueError:
        return str(raw)


def format_sale_text(payload: dict, *, timezone_name: str = "UTC") -> str:
    """Plain-text sale summary. Never includes invoice files/PDFs."""
    lines = ["Stock & POS — New Sale"]
    lines.append(f"Invoice: {payload.get('invoice_no', '-')}")
    lines.append(f"Date: {_stamp(payload.get('occurred_at', ''), timezone_name)}")
    lines.append(f"Customer: {payload.get('customer') or 'Walk-in Customer'}")
    currency = payload.get("currency") or "USD"
    rate = payload.get("exchange_rate") or "1"
    if currency != "USD" and Decimal(str(rate)) != Decimal("1"):
        lines.append(f"Currency: {currency} (rate {rate})")
    else:
        lines.append(f"Currency: {currency}")
    if payload.get("item_count") is not None:
        lines.append(f"Items: {payload['item_count']}")
    if payload.get("subtotal") is not None:
        lines.append(f"Subtotal: {payload['subtotal']}")
    if payload.get("discount") is not None and Decimal(payload["discount"] or "0") != 0:
        lines.append(f"Discount: {payload['discount']}")
    if payload.get("delivery_price") is not None and Decimal(payload["delivery_price"] or "0") != 0:
        lines.append(f"Delivery: {payload['delivery_price']}")
    lines.append(f"Total: {payload.get('total', '-')}")
    lines.append(f"Paid: {payload.get('paid', '-')}")
    lines.append(f"Method: {payload.get('payment_method', '-')}")
    if payload.get("debt") is not None and Decimal(payload["debt"] or "0") > 0:
        lines.append(f"Debt: {payload['debt']}")
    if payload.get("cashier"):
        lines.append(f"Cashier: {payload['cashier']}")
    return "\n".join(lines)


def format_purchase_text(payload: dict, *, timezone_name: str = "UTC") -> str:
    """Plain-text purchase (Stock In) summary."""
    lines = ["Stock & POS — Stock In"]
    lines.append(f"Document: {payload.get('document_no', '-')}")
    lines.append(f"Date: {_stamp(payload.get('occurred_at', ''), timezone_name)}")
    if payload.get("supplier"):
        lines.append(f"Supplier: {payload['supplier']}")
    currency = payload.get("currency") or "USD"
    lines.append(f"Currency: {currency}")
    if payload.get("item_count") is not None:
        lines.append(f"Items: {payload['item_count']}")
    if payload.get("subtotal") is not None:
        lines.append(f"Subtotal: {payload['subtotal']}")
    if payload.get("discount") is not None and Decimal(payload["discount"] or "0") != 0:
        lines.append(f"Discount: {payload['discount']}")
    if payload.get("tax") is not None and Decimal(payload["tax"] or "0") != 0:
        lines.append(f"Tax: {payload['tax']}")
    lines.append(f"Total: {payload.get('total', '-')}")
    lines.append(f"Paid: {payload.get('paid', '-')}")
    if payload.get("debt") is not None and Decimal(payload["debt"] or "0") > 0:
        lines.append(f"Supplier debt: {payload['debt']}")
    if payload.get("user"):
        lines.append(f"Recorded by: {payload['user']}")
    return "\n".join(lines)


def format_payment_text(payload: dict, *, timezone_name: str = "UTC") -> str:
    """Plain-text debt-payment summary (no invoice files — text only)."""
    lines = ["Stock & POS — Debt Payment"]
    lines.append(f"Invoice: {payload.get('invoice_no', '-')}")
    if payload.get("payment_no"):
        lines.append(f"Payment: {payload['payment_no']}")
    lines.append(f"Date: {_stamp(payload.get('occurred_at', ''), timezone_name)}")
    lines.append(f"Customer: {payload.get('customer') or 'Walk-in Customer'}")
    lines.append(f"Total: {payload.get('total', '-')}")
    lines.append(f"Paid: {payload.get('paid', '-')}")
    lines.append(f"Method: {payload.get('payment_method', '-')}")
    if payload.get("remaining") is not None:
        lines.append(f"Remaining debt: {payload['remaining']}")
    if payload.get("cashier"):
        lines.append(f"Cashier: {payload['cashier']}")
    return "\n".join(lines)


def format_supplier_payment_text(payload: dict, *, timezone_name: str = "UTC") -> str:
    """Plain-text supplier debt-payment summary."""
    lines = ["Stock & POS — Supplier Payment"]
    lines.append(f"Document: {payload.get('document_no') or '-'}")
    if payload.get("payment_no"):
        lines.append(f"Payment: {payload['payment_no']}")
    lines.append(f"Date: {_stamp(payload.get('occurred_at', ''), timezone_name)}")
    if payload.get("supplier"):
        lines.append(f"Supplier: {payload['supplier']}")
    lines.append(f"Total: {payload.get('total', '-')}")
    lines.append(f"Paid: {payload.get('paid', '-')}")
    lines.append(f"Method: {payload.get('payment_method', '-')}")
    if payload.get("remaining") is not None:
        lines.append(f"Remaining debt: {payload['remaining']}")
    if payload.get("cashier"):
        lines.append(f"Cashier: {payload['cashier']}")
    return "\n".join(lines)


# ------------------------------------------------------------- daily summary


async def daily_summary_totals(session: AsyncSession, *, day: date | None = None) -> dict:
    """Aggregated operational numbers for one local day.

    USD and KHR totals are NEVER summed together — every amount stays in its
    document currency and the summary reports both columns separately.
    """
    from app.modules.customers.models import CustomerDebt
    from app.modules.delivery.models import DeliveryNote
    from app.modules.pos.models import Sale
    from app.modules.stock.models import Product, StockBalance, StockTransaction, StockTransactionItem
    from app.modules.suppliers.models import SupplierDebt

    day = day or _local_today(
        str(await get_setting_value(session, "system", "timezone", "UTC") or "UTC")
    )
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = datetime(day.year, day.month, day.day + 1, tzinfo=timezone.utc)

    async def currency_totals(stmt_model, date_col, total_expr=None):
        rows = await session.execute(
            select(
                stmt_model.currency,
                func.count(),
                func.coalesce(func.sum(total_expr if total_expr is not None else stmt_model.grand_total), 0),
            )
            .where(date_col >= day_start, date_col < day_end)
            .group_by(stmt_model.currency)
        )
        out: dict[str, dict[str, object]] = {}
        for currency, count, total in rows.all():
            out[str(currency)] = {"count": int(count), "total": Decimal(total).quantize(Decimal("0.01"))}
        return out

    sales = await currency_totals(Sale, Sale.sale_date)
    # Purchase total per document = sum(item.line_total) − discount + tax.
    items_subtotal = (
        select(
            StockTransactionItem.stock_transaction_id.label("tx_id"),
            func.coalesce(func.sum(StockTransactionItem.line_total), 0).label("subtotal"),
        )
        .group_by(StockTransactionItem.stock_transaction_id)
        .subquery()
    )
    purchase_rows = await session.execute(
        select(
            StockTransaction.currency,
            func.count(),
            func.coalesce(
                func.sum(items_subtotal.c.subtotal - StockTransaction.discount_amount + StockTransaction.tax_amount),
                0,
            ),
        )
        .join(items_subtotal, items_subtotal.c.tx_id == StockTransaction.id)
        .where(
            StockTransaction.transaction_date >= day_start,
            StockTransaction.transaction_date < day_end,
            StockTransaction.transaction_type == "STOCK_IN",
        )
        .group_by(StockTransaction.currency)
    )
    purchases = {
        str(currency): {"count": int(count), "total": Decimal(total).quantize(Decimal("0.01"))}
        for currency, count, total in purchase_rows.all()
    }

    customer_debt_total = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(CustomerDebt.remaining_amount), 0)).where(
                    CustomerDebt.status != "PAID"
                )
            )
        ).scalar_one()
    )
    supplier_debt_total = Decimal(
        (
            await session.execute(
                select(func.coalesce(func.sum(SupplierDebt.remaining_amount), 0)).where(
                    SupplierDebt.status != "PAID"
                )
            )
        ).scalar_one()
    )

    deliveries = (
        await session.execute(
            select(DeliveryNote.status, func.count()).group_by(DeliveryNote.status)
        )
    ).all()
    delivery_counts = {str(status): int(count) for status, count in deliveries}
    delivered_count = delivery_counts.get("DELIVERED", 0)
    pending_delivery_count = sum(
        count
        for status, count in delivery_counts.items()
        if status not in ("DELIVERED", "RETURNED", "FAILED")
    )

    out_of_stock = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Product)
                .join(StockBalance, StockBalance.product_id == Product.id)
                .where(
                    Product.status == "ACTIVE",
                    StockBalance.quantity <= 0,
                )
            )
        ).scalar_one()
    )

    return {
        "day": day.isoformat(),
        "sales": {currency: {"count": row["count"], "total": str(row["total"])} for currency, row in sales.items()},
        "purchases": {currency: {"count": row["count"], "total": str(row["total"])} for currency, row in purchases.items()},
        "customer_debt_total": str(customer_debt_total.quantize(Decimal("0.01"))),
        "supplier_debt_total": str(supplier_debt_total.quantize(Decimal("0.01"))),
        "delivered_count": delivered_count,
        "pending_delivery_count": pending_delivery_count,
        "out_of_stock_count": out_of_stock,
    }


def format_daily_summary_text(summary: dict) -> str:
    """Render the daily summary; USD and KHR columns are kept separate."""
    lines = [f"Stock & POS — Daily Summary {summary.get('day', '')}"]

    sales = summary.get("sales") or {}
    sale_count = sum(int(row["count"]) for row in sales.values())
    lines.append(f"Sales: {sale_count}")
    if sales.get("USD"):
        lines.append(f"  USD sales: {sales['USD']['total']}")
    if sales.get("KHR"):
        lines.append(f"  KHR sales: {sales['KHR']['total']}")

    purchases = summary.get("purchases") or {}
    purchase_count = sum(int(row["count"]) for row in purchases.values())
    lines.append(f"Purchases: {purchase_count}")
    if purchases.get("USD"):
        lines.append(f"  USD purchases: {purchases['USD']['total']}")
    if purchases.get("KHR"):
        lines.append(f"  KHR purchases: {purchases['KHR']['total']}")

    lines.append(f"Customer debt outstanding: {summary.get('customer_debt_total', '-')}")
    lines.append(f"Supplier debt outstanding: {summary.get('supplier_debt_total', '-')}")
    lines.append(f"Delivered: {summary.get('delivered_count', 0)}")
    lines.append(f"Pending deliveries: {summary.get('pending_delivery_count', 0)}")
    lines.append(f"Out-of-stock products: {summary.get('out_of_stock_count', 0)}")
    return "\n".join(lines)


async def send_daily_summary(session: AsyncSession, *, sender=None, day: date | None = None) -> dict:
    """Build and broadcast the daily summary. Never raises into the scheduler."""
    try:
        if not await get_setting_value(session, "telegram", "daily_summary_enabled", False):
            return {"enabled": False, "sent": 0}
        if not await telegram_enabled(session):
            return {"enabled": False, "sent": 0}
        summary = await daily_summary_totals(session, day=day)
        text = format_daily_summary_text(summary)
        sent = await _broadcast(session, text, sender=sender)
        return {"enabled": True, "sent": sent, "summary": summary}
    except Exception:
        logger.exception("Telegram daily summary failed")
        return {"enabled": False, "sent": 0, "error": True}
