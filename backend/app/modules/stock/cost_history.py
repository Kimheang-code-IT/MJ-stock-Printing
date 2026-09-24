"""Read-only product cost history derived from confirmed Stock In lots.

There is deliberately no write path — costs are created only by Stock In
(or its edits / purchase returns).
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.stock.models import Product, StockTransaction, StockTransactionItem
from app.shared.pagination.params import parse_date_range

TWO = Decimal("0.01")


async def product_cost_history(
    session: AsyncSession,
    *,
    product_id: uuid.UUID,
    q: str | None,
    start: str | None,
    end: str | None,
    page: int,
    limit: int,
) -> tuple[list[dict], int]:
    """Read-only cost-price versions derived from confirmed Stock In lots.

    Lots are sorted oldest → newest to assign version 1, 2, 3… and returned
    newest first.
    """
    result = await session.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if product is None:
        raise NotFoundError("Product not found")

    conditions = [
        StockTransactionItem.product_id == product_id,
        StockTransaction.transaction_type == "STOCK_IN",
        StockTransaction.status == "CONFIRMED",
    ]
    start_at, end_at = parse_date_range(start, end)
    if start_at is not None:
        conditions.append(StockTransaction.transaction_date >= start_at)
    if end_at is not None:
        conditions.append(StockTransaction.transaction_date <= end_at)
    if q and q.strip():
        conditions.append(StockTransaction.document_no.ilike(f"%{q.strip()}%"))

    rows = (
        await session.execute(
            select(StockTransactionItem, StockTransaction.transaction_date, StockTransaction.document_no)
            .join(StockTransaction, StockTransaction.id == StockTransactionItem.stock_transaction_id)
            .where(*conditions)
            .order_by(StockTransaction.transaction_date.asc(), StockTransactionItem.created_at.asc())
        )
    ).all()

    lots = []
    for version, (item, transaction_date, document_no) in enumerate(rows, start=1):
        qty = Decimal(item.quantity)
        unit_cost = Decimal(item.unit_cost)
        lots.append(
            {
                "id": item.id,
                "date": transaction_date,
                "product_id": product_id,
                "productId": product_id,
                "product_name": product.name,
                "unit_cost": unit_cost,
                "unitCost": unit_cost,
                "qty": qty,
                "amount": (qty * unit_cost).quantize(TWO, rounding=ROUND_HALF_UP),
                "version": version,
                "document_no": document_no,
                "documentNo": document_no,
            }
        )
    lots.reverse()

    total = len(lots)
    offset = (page - 1) * limit
    return lots[offset : offset + limit], total
