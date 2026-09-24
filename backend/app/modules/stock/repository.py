from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.image.service import resolve_media_url
from app.modules.stock.models import Product, StockBalance, StockMovement


# Movement-kind grouping for the stock read model (spec section 2.1.5):
# Stock In (inbound), Stock Out (non-damage outbound), Damage.
STOCK_IN_TYPES = ("STOCK_IN", "SALE_RETURN", "ADJUSTMENT_IN")
STOCK_OUT_TYPES = ("SALE", "PURCHASE_RETURN", "ADJUSTMENT_OUT")
DAMAGE_TYPES = ("DAMAGE",)


def _product_aggregates(product_id: uuid.UUID, grouped: dict) -> dict:
    row = grouped.get(product_id)
    if row is None:
        return {
            "stock_in_qty": Decimal("0"),
            "stock_out_qty": Decimal("0"),
            "damage_qty": Decimal("0"),
        }
    return {
        "stock_in_qty": Decimal(row["stock_in_qty"]).quantize(Decimal("0.0001")),
        "stock_out_qty": Decimal(row["stock_out_qty"]).quantize(Decimal("0.0001")),
        "damage_qty": Decimal(row["damage_qty"]).quantize(Decimal("0.0001")),
    }


def product_to_out(product: Product, *, grouped: dict | None = None) -> dict:
    aggregates = _product_aggregates(product.id, grouped or {})
    data = {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "category_id": product.category_id,
        "category_name": product.category_ref.name if product.category_ref else None,
        "brand_id": product.brand_id,
        "brand_name": product.brand_ref.name if product.brand_ref else None,
        "supplier_id": product.supplier_id,
        "supplier_name": product.supplier_ref.name if product.supplier_ref else None,
        "cost_price": product.cost_price,
        "selling_price": product.selling_price,
        "minimum_stock": product.minimum_stock,
        "image_object_key": product.image_object_key,
        "image_url": resolve_media_url(product.image_object_key),
        "status": product.status,
        "note": product.note,
        "quantity": product.balance.quantity if product.balance else Decimal("0"),
        "average_cost": product.balance.average_cost if product.balance else Decimal("0.00"),
        "created_at": product.created_at,
        **aggregates,
    }
    return data


def _product_order_by(sort: str | None) -> tuple:
    """Product-list sort. `sort` is `field` or `-field` (descending).
    Unknown fields fall back to the stable default: name, id."""
    columns = {
        "name": Product.name,
        "status": Product.status,
        "cost_price": Product.cost_price,
        "selling_price": Product.selling_price,
        "created_at": Product.created_at,
    }
    if sort:
        column = columns.get(sort.lstrip("+-").strip())
        if column is not None:
            if sort.startswith("-"):
                return (column.desc(), Product.id.desc())
            return (column.asc(), Product.id.asc())
    return (Product.name.asc(), Product.id.asc())


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self, *, q, category_id, brand_id, status, page, limit, sort=None
    ) -> tuple[list[Product], int]:
        stmt = select(Product)
        count_stmt = select(func.count()).select_from(Product)
        if q:
            pattern = f"%{q.strip()}%"
            # Name-first search plus the optional internal sku code.
            condition = Product.name.ilike(pattern) | Product.sku.ilike(pattern)
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
            count_stmt = count_stmt.where(Product.category_id == category_id)
        if brand_id is not None:
            stmt = stmt.where(Product.brand_id == brand_id)
            count_stmt = count_stmt.where(Product.brand_id == brand_id)
        if status:
            stmt = stmt.where(Product.status == status)
            count_stmt = count_stmt.where(Product.status == status)
        total = (await self.session.execute(count_stmt)).scalar_one()
        order_by = _product_order_by(sort)
        rows = await self.session.execute(
            stmt.order_by(*order_by).offset((page - 1) * limit).limit(limit)
        )
        return list(rows.scalars().all()), int(total)

    async def get(self, product_id: uuid.UUID) -> Product | None:
        return await self.session.get(Product, product_id)

    async def get_by_sku(self, sku: str) -> Product | None:
        result = await self.session.execute(select(Product).where(Product.sku == sku))
        return result.scalar_one_or_none()

    async def ensure_balance(self, product_id: uuid.UUID) -> StockBalance:
        result = await self.session.execute(
            select(StockBalance).where(StockBalance.product_id == product_id)
        )
        balance = result.scalar_one_or_none()
        if balance is None:
            balance = StockBalance(product_id=product_id, quantity=Decimal("0"), average_cost=Decimal("0.00"))
            self.session.add(balance)
            await self.session.flush()
        return balance

    async def count_movements(self, product_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(StockMovement).where(StockMovement.product_id == product_id)
        )
        return int(result.scalar_one())

    async def count_sale_items(self, product_id: uuid.UUID) -> int:
        from app.modules.pos.models import SaleItem

        result = await self.session.execute(
            select(func.count()).select_from(SaleItem).where(SaleItem.product_id == product_id)
        )
        return int(result.scalar_one())

    async def count_transaction_items(self, product_id: uuid.UUID) -> int:
        from app.modules.stock.models import StockTransactionItem

        result = await self.session.execute(
            select(func.count())
            .select_from(StockTransactionItem)
            .where(StockTransactionItem.product_id == product_id)
        )
        return int(result.scalar_one())

    async def count_purchase_return_items(self, product_id: uuid.UUID) -> int:
        from app.modules.stock.models import PurchaseReturnItem

        result = await self.session.execute(
            select(func.count())
            .select_from(PurchaseReturnItem)
            .where(PurchaseReturnItem.product_id == product_id)
        )
        return int(result.scalar_one())

    async def count_delivery_items(self, product_id: uuid.UUID) -> int:
        from app.modules.delivery.models import DeliveryNoteItem

        result = await self.session.execute(
            select(func.count())
            .select_from(DeliveryNoteItem)
            .where(DeliveryNoteItem.product_id == product_id)
        )
        return int(result.scalar_one())

    async def aggregate_movements(self, product_ids: list[uuid.UUID]) -> dict:
        """Per-product stock read-model aggregates.

        Returns {product_id: {stock_in_qty, stock_out_qty, damage_qty}}.
        stock_in/out/damage derive from the immutable stock_movements ledger.
        """
        if not product_ids:
            return {}
        stock_in = func.coalesce(
            func.sum(
                case(
                    (StockMovement.movement_type.in_(STOCK_IN_TYPES), StockMovement.quantity_delta),
                    else_=0,
                )
            ),
            0,
        )
        stock_out = func.coalesce(
            func.sum(
                case(
                    (StockMovement.movement_type.in_(STOCK_OUT_TYPES), -StockMovement.quantity_delta),
                    else_=0,
                )
            ),
            0,
        )
        damage = func.coalesce(
            func.sum(
                case(
                    (StockMovement.movement_type.in_(DAMAGE_TYPES), -StockMovement.quantity_delta),
                    else_=0,
                )
            ),
            0,
        )
        movement_rows = await self.session.execute(
            select(
                StockMovement.product_id,
                stock_in.label("stock_in_qty"),
                stock_out.label("stock_out_qty"),
                damage.label("damage_qty"),
            )
            .where(StockMovement.product_id.in_(product_ids))
            .group_by(StockMovement.product_id)
        )
        return {
            row.product_id: {
                "stock_in_qty": row.stock_in_qty,
                "stock_out_qty": row.stock_out_qty,
                "damage_qty": row.damage_qty,
            }
            for row in movement_rows
        }