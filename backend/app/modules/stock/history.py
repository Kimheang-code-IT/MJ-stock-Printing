"""Product stock-history read model — spec section 2.1.5.

Clicking Stock In / Stock Out / Damage / Current Stock on the Stock list opens
a history dialog filtered to that product and movement kind. Rows are compact:
date, type, product, unit, unit price, qty, reference, user, note.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.modules.auth.models import User
from app.modules.stock.models import StockMovement
from app.shared.pagination.params import parse_date_range

# kind -> movement types. Every canonical movement type maps to exactly one
# dialog kind so the Stock list columns and the dialogs always agree:
# Stock In = STOCK_IN + SALE_RETURN, Stock Out = SALE + PURCHASE_RETURN,
# Damage = DAMAGE only.
MOVEMENT_KINDS: dict[str, tuple[str, ...]] = {
    "stock_in": ("STOCK_IN", "SALE_RETURN"),
    "stock_out": ("SALE", "PURCHASE_RETURN"),
    "damage": ("DAMAGE",),
    "all": (),  # empty tuple = no type filter (full movement history)
}


def movement_kind_types(kind: str | None) -> tuple[str, ...]:
    """Resolve a history-dialog kind filter to movement types."""
    normalized = (kind or "all").strip().lower()
    if normalized not in MOVEMENT_KINDS:
        raise ValueError(f"Unknown history kind '{kind}'")
    return MOVEMENT_KINDS[normalized]


def movement_kind(movement_type: str) -> str:
    """Map a movement type back to its dialog kind."""
    for kind, types in MOVEMENT_KINDS.items():
        if movement_type in types:
            return kind
    return "all"


def _display_type(movement_type: str) -> str:
    """Labels the Stock list dialogs already filter on:
    Stock In / Sale Return / Sale / Damage."""
    return movement_type.replace("_", " ").title()


async def product_history(
    session: AsyncSession,
    *,
    product_id: uuid.UUID,
    kind: str | None,
    start: str | None,
    end: str | None,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
    """Compact, paginated stock-history rows for one product."""
    movement_types = movement_kind_types(kind)

    conditions = [StockMovement.product_id == product_id]
    if movement_types:
        conditions.append(StockMovement.movement_type.in_(movement_types))
    start_at, end_at = parse_date_range(start, end)
    if start_at is not None:
        conditions.append(StockMovement.created_at >= start_at)
    if end_at is not None:
        conditions.append(StockMovement.created_at <= end_at)

    count_stmt = select(func.count()).select_from(StockMovement).where(*conditions)
    total = (await session.execute(count_stmt)).scalar_one()

    rows = await session.execute(
        select(StockMovement, User.full_name)
        .join(User, User.id == StockMovement.created_by, isouter=True)
        .where(*conditions)
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )

    history: list[dict] = []
    for movement, user_name in rows.all():
        product = movement.product_ref
        history.append(
            {
                "id": movement.id,
                "date": movement.created_at,
                "type": _display_type(movement.movement_type),
                "kind": movement_kind(movement.movement_type),
                "qty": movement.quantity_delta,
                "product": product.name if product else "",
                "unit_price": movement.unit_cost,
                "reference": movement.document_no,
                "reference_type": movement.reference_type,
                "reference_id": movement.reference_id,
                "user": user_name,
                "note": movement.note,
            }
        )
    return history, int(total)


async def movement_invoice(session: AsyncSession, movement_id: uuid.UUID) -> dict:
    """Read-only invoice detail behind one SALE movement (Stock Out dialog).

    Reuses the POS receipt payload so the dialog and the printed invoice can
    never disagree. Movements that are not a POS sale (Stock In, Purchase
    Return, Damage, …) have no invoice and are rejected.
    """
    movement = await session.get(StockMovement, movement_id)
    if movement is None:
        raise NotFoundError("Stock movement not found")
    if movement.reference_type != "sale":
        raise ValidationError("This stock movement is not linked to a sale invoice")

    from app.modules.pos.models import Sale
    from app.modules.pos.service import POSService

    sale = await session.get(Sale, movement.reference_id)
    if sale is None:
        raise NotFoundError("Sale not found for this stock movement")
    return await POSService(session).build_receipt(sale)
