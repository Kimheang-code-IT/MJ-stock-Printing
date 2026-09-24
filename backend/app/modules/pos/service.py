"""POS service: product search, atomic sale completion, returns.

The sale transaction commits sale, items, payment/customer debt, stock
movements, balances, invoice sequence, and audit together — or not at all.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.auth.models import User
from app.modules.customers.models import Customer, CustomerDebt
from app.modules.pos.models import Sale, SaleItem, SaleReturn, SaleReturnItem, Payment
from app.modules.pos.schemas import (
    POSProductOut,
    SaleItemOut,
    SaleOut,
    SaleReturnItemOut,
    SaleReturnOut,
)
from app.modules.stock.models import Product
from app.modules.stock.repository import ProductRepository
from app.modules.stock.service import (
    _lock_balance,
    allow_negative_stock,
    apply_stock_movement,
)
from app.shared.audit.service import record_audit
from app.shared.documents import allocate_document_number

logger = logging.getLogger("mj.pos")


TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def _q2(value) -> Decimal:
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def _q4(value) -> Decimal:
    return Decimal(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def _to_sale_currency(usd_price, exchange_rate) -> Decimal:
    """Product prices are USD; the POS line is priced in the sale currency
    (KHR documents convert by the sale exchange rate)."""
    return (Decimal(usd_price) * Decimal(exchange_rate or 1)).quantize(TWO, rounding=ROUND_HALF_UP)


async def get_walk_in_customer(session: AsyncSession) -> Customer | None:
    result = await session.execute(select(Customer).where(Customer.is_walk_in.is_(True)))
    return result.scalar_one_or_none()


def sale_to_out(
    sale: Sale,
    customer_name: str | None = None,
    change_amount: Decimal = Decimal("0"),
    items: list[SaleItem] | None = None,
) -> SaleOut:
    resolved_items = items if items is not None else list(sale.items)
    return SaleOut(
        id=sale.id,
        invoice_no=sale.invoice_no,
        customer_id=sale.customer_id,
        customer_name=customer_name,
        sale_date=sale.sale_date,
        subtotal=sale.subtotal,
        delivery_price=getattr(sale, "delivery_price", Decimal("0")),
        deliveryPrice=getattr(sale, "delivery_price", Decimal("0")),
        grand_total=sale.grand_total,
        paid_amount=sale.paid_amount,
        debt_amount=sale.debt_amount,
        payment_status=sale.payment_status,
        sale_status=sale.sale_status,
        cashier_id=sale.cashier_id,
        note=sale.note,
        change_amount=change_amount,
        currency=getattr(sale, "currency", "USD"),
        exchange_rate=getattr(sale, "exchange_rate", Decimal("1")),
        items=[SaleItemOut.model_validate(item) for item in resolved_items],
    )


class POSService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.products = ProductRepository(session)

    # ---------------------------------------------------------------- search

    async def search_products(self, *, q: str | None, category_id: uuid.UUID | None, limit: int) -> list[POSProductOut]:
        stmt = (
            select(Product)
            .where(Product.status == "ACTIVE")
            .order_by(Product.name)
            .limit(max(1, min(limit, 50)))
        )
        if q:
            needle = q.strip()
            pattern = f"%{needle}%"
            stmt = stmt.where(Product.name.ilike(pattern) | Product.sku.ilike(pattern))
            rows = list((await self.session.execute(stmt)).scalars().all())
            return [await self._product_out(p) for p in rows]
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        rows = await self.session.execute(stmt)
        return [await self._product_out(p) for p in rows.scalars().all()]

    async def _product_out(self, product: Product) -> POSProductOut:
        from app.modules.image.service import resolve_media_url

        balance = product.balance
        return POSProductOut(
            id=product.id,
            sku=product.sku,
            name=product.name,
            category_id=product.category_id,
            category_name=product.category_ref.name if product.category_ref else None,
            selling_price=product.selling_price,
            quantity=balance.quantity if balance else Decimal("0"),
            image_object_key=product.image_object_key,
            image_url=resolve_media_url(product.image_object_key),
            status=product.status,
        )

    # ------------------------------------------------------------------ sale

    async def complete_sale(self, payload, *, actor: User) -> SaleOut:
        customer = await self._resolve_customer(payload)
        products: dict[uuid.UUID, Product] = {}
        for item in payload.items:
            if item.product_id in products:
                raise ValidationError("Duplicate product in cart", field_errors={"items": "Duplicate product"})
            product = await self.products.get(item.product_id)
            if product is None:
                raise NotFoundError("Product not found")
            if product.status != "ACTIVE":
                raise ValidationError("Inactive products cannot be sold", field_errors={"items": "Product inactive"})
            products[item.product_id] = product

        negative_ok = await allow_negative_stock(self.session)
        invoice_no = await allocate_document_number(self.session, "INVOICE")

        sale = Sale(
            invoice_no=invoice_no,
            customer_id=customer.id,
            sale_date=payload.sale_date or datetime.now(timezone.utc),
            cashier_id=actor.id,
            note=payload.note,
            delivery_price=_q2(payload.delivery_price),
            subtotal=Decimal("0.00"),
            grand_total=Decimal("0.00"),
            payment_status="UNPAID",
            currency=payload.currency,
            exchange_rate=payload.exchange_rate,
        )
        self.session.add(sale)
        await self.session.flush()

        subtotal = Decimal("0.00")
        item_rows: list[SaleItem] = []
        for item in payload.items:
            product = products[item.product_id]
            quantity = item.quantity

            # POS charges the product's selling price (converted to the
            # document currency) unless the cashier overrides the line.
            default_price = product.selling_price
            quantity = _q4(quantity)
            if quantity <= 0:
                raise ValidationError("Line quantity must be greater than zero", field_errors={"items": "Invalid quantity"})

            # Sold-by-area line: Height × Width (metres) becomes the billed m².
            height = item.height
            width = item.width
            area_m2 = None
            if (height is None) != (width is None):
                raise ValidationError(
                    "Height and width must be provided together",
                    field_errors={"items": "Height and width required"},
                )
            if height is not None and width is not None:
                area_m2 = _q4(Decimal(height) * Decimal(width))
                quantity = area_m2
                if quantity <= 0:
                    raise ValidationError("Line area must be greater than zero", field_errors={"items": "Invalid area"})

            if item.unit_price is None:
                unit_price = _to_sale_currency(default_price, payload.exchange_rate)
            else:
                unit_price = item.unit_price
            gross = (quantity * unit_price).quantize(TWO, rounding=ROUND_HALF_UP)

            line_total = gross

            provisional = SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                product_name=product.name,
                sku=product.sku,
                height=height,
                width=width,
                area_m2=area_m2,
                quantity=quantity,
                unit_price=unit_price,
                unit_cost=Decimal("0.00"),
                line_total=line_total,
            )
            self.session.add(provisional)
            await self.session.flush()
            # Cost snapshot: the materialized weighted average cost, falling
            # back to the product's cost price when no stock cost exists.
            balance = await _lock_balance(self.session, product.id)
            line_cost = _q2(balance.average_cost or product.cost_price)
            provisional.unit_cost = line_cost
            await self.session.flush()
            balance = await apply_stock_movement(
                self.session,
                product_id=product.id,
                movement_type="SALE",
                quantity_delta=-quantity,
                unit_cost=line_cost,
                reference_type="sale",
                reference_id=sale.id,
                created_by=actor.id,
                document_no=invoice_no,
                allow_negative=negative_ok,
            )
            row = provisional
            item_rows.append(row)
            subtotal += gross

        delivery_price = _q2(payload.delivery_price)
        grand_total = subtotal + delivery_price
        sale.subtotal = _q2(subtotal)
        sale.grand_total = _q2(grand_total)

        # ---- settle included open debts from `deposit` (separate from sale) ----
        # amount_received / paidAmount applies only to THIS sale's grand_total.
        # deposit is the budget for selected prior-debt payments and never
        # inflates the current sale total or default Paid now.
        remaining_deposit = _q2(payload.deposit)
        for debt_id in payload.included_debt_ids:
            debt_result = await self.session.execute(
                select(CustomerDebt).where(CustomerDebt.id == debt_id).with_for_update()
            )
            debt = debt_result.scalar_one_or_none()
            if debt is None:
                raise NotFoundError("Included customer debt not found")
            if debt.customer_id != customer.id:
                raise ValidationError(
                    "Included debts must belong to the sale's customer",
                    field_errors={"included_debt_ids": "Debt belongs to another customer"},
                )
            if debt.remaining_amount <= 0 or debt.status == "PAID":
                continue
            applied = min(debt.remaining_amount, remaining_deposit)
            if applied > 0:
                debt.paid_amount = debt.paid_amount + applied
                debt.remaining_amount = debt.remaining_amount - applied
                debt.status = "PAID" if debt.remaining_amount == 0 else "PARTIAL"
                await self._create_payment(
                    payment_no=await allocate_document_number(self.session, "CUSTOMER_DEBT_PAYMENT"),
                    sale_id=None,
                    customer_id=customer.id,
                    payment_type="CUSTOMER_DEBT_PAYMENT",
                    payment_method=payload.payment_method if payload.payment_method != "CUSTOMER_DEBT" else (payload.deposit_method or "CASH"),
                    amount=applied,
                    reference_no=sale.invoice_no,
                    actor=actor,
                    customer_debt_id=debt.id,
                )
                await record_audit(
                    self.session,
                    action="customer_debt_payment",
                    module="customers",
                    user_id=actor.id,
                    entity_type="customer_debt",
                    entity_id=debt.id,
                    new_values={
                        "invoice_no": debt.invoice_no,
                        "applied": str(applied),
                        "remaining": str(debt.remaining_amount),
                        "via_sale": sale.invoice_no,
                    },
                )
                remaining_deposit -= applied

        paid_for_sale = max(Decimal("0.00"), min(_q2(payload.amount_received), sale.grand_total))
        debt_amount = sale.grand_total - paid_for_sale

        debt: CustomerDebt | None = None
        change_amount = Decimal("0.00")
        if debt_amount > 0 and customer.is_walk_in:
            raise ValidationError(
                "The walk-in customer cannot make a debt purchase",
                field_errors={"customer_id": "Select a registered customer"},
            )
        if debt_amount > 0:
            debt = CustomerDebt(
                customer_id=customer.id,
                sale_id=sale.id,
                invoice_no=sale.invoice_no,
                original_amount=sale.grand_total,
                paid_amount=paid_for_sale,
                remaining_amount=debt_amount,
                due_date=payload.due_date,
                status="UNPAID" if paid_for_sale == 0 else "PARTIAL",
                currency=sale.currency,
                exchange_rate=sale.exchange_rate,
            )
            self.session.add(debt)
            await self.session.flush()

        sale.paid_amount = paid_for_sale
        sale.debt_amount = debt_amount
        sale.payment_status = "PAID" if debt_amount == 0 else ("PARTIAL" if paid_for_sale > 0 else "UNPAID")

        if paid_for_sale > 0:
            await self._create_payment(
                payment_no=await allocate_document_number(self.session, "CUSTOMER_DEBT_PAYMENT"),
                sale_id=sale.id,
                customer_id=customer.id,
                payment_type="SALE_PAYMENT",
                payment_method=payload.payment_method
                if payload.payment_method != "CUSTOMER_DEBT"
                else (payload.deposit_method or "CASH"),
                amount=paid_for_sale,
                reference_no=payload.reference_no,
                actor=actor,
                customer_debt_id=debt.id if debt else None,
            )
        if payload.payment_method in ("CASH", "BANK_QR"):
            change_amount = _q2(max(Decimal("0.00"), payload.amount_received - sale.grand_total))

        await record_audit(
            self.session,
            action="sale",
            module="pos",
            user_id=actor.id,
            entity_type="sale",
            entity_id=sale.id,
            new_values={
                "invoice_no": invoice_no,
                "grand_total": str(sale.grand_total),
                "payment_method": payload.payment_method,
            },
        )
        await self.session.commit()

        # Telegram sale notification strictly AFTER commit: a notification
        # failure must never roll back the committed sale. Debt sales notify
        # through customer debt payments instead (spec §3.6.2).
        if payload.payment_method in ("CASH", "BANK_QR"):
            from app.shared.telegram.service import notify_sale

            await notify_sale(
                self.session,
                invoice_no=sale.invoice_no,
                occurred_at=sale.sale_date,
                customer=customer.name,
                currency=sale.currency,
                exchange_rate=sale.exchange_rate,
                subtotal=sale.subtotal,
                delivery_price=sale.delivery_price,
                total=sale.grand_total,
                paid=sale.paid_amount,
                payment_method=payload.payment_method,
                debt=sale.debt_amount,
                cashier=actor.full_name,
                item_count=len(item_rows),
                customer_phone=getattr(customer, "phone", None),
                items=[
                    {
                        "name": item.product_name,
                        "quantity": str(item.quantity),
                        "unit_price": str(item.unit_price),
                        "line_total": str(item.line_total),
                    }
                    for item in item_rows
                ],
            )
        return sale_to_out(sale, customer_name=customer.name, change_amount=change_amount, items=item_rows)

    async def update_sale(self, sale_id, payload, *, actor: User) -> SaleOut:
        """Edit a completed sale: reverse the original stock (append-only
        compensating movements) then re-apply the new lines, quantities and
        prices. The customer and immutable payments are kept;
        the outstanding customer debt is recalculated from the new total."""
        result = await self.session.execute(
            select(Sale).where(Sale.id == sale_id).with_for_update()
        )
        sale = result.scalar_one_or_none()
        if sale is None:
            raise NotFoundError("Sale not found")
        if sale.sale_status != "COMPLETED":
            raise ConflictError("Only completed sales can be edited")
        existing_items = list(sale.items)
        if any(Decimal(item.returned_quantity or 0) > 0 for item in existing_items):
            raise ConflictError("Sales with returns cannot be edited")
        # Delivery-note items RESTRICT-reference sale_items, so deleting the
        # old lines would raise a FK violation (500). Reject the edit cleanly.
        from app.modules.delivery.models import DeliveryNoteItem

        attached = await self.session.execute(
            select(func.count())
            .select_from(DeliveryNoteItem)
            .where(DeliveryNoteItem.sale_item_id.in_([item.id for item in existing_items]))
        )
        if int(attached.scalar_one() or 0) > 0:
            raise ConflictError("Sales with delivery notes cannot be edited")

        customer = await self.session.get(Customer, sale.customer_id)
        if customer is None:
            raise NotFoundError("Customer not found")

        products: dict[uuid.UUID, Product] = {}
        for item in payload.items:
            if item.product_id in products:
                raise ValidationError("Duplicate product in cart", field_errors={"items": "Duplicate product"})
            product = await self.products.get(item.product_id)
            if product is None:
                raise NotFoundError("Product not found")
            if product.status != "ACTIVE":
                raise ValidationError("Inactive products cannot be sold", field_errors={"items": "Product inactive"})
            products[item.product_id] = product

        negative_ok = await allow_negative_stock(self.session)

        # 1) Reverse the original lines: append compensating SALE_RETURN
        #    movements (the old SALE rows are never mutated), then drop the old
        #    items so the new set can be applied.
        for row in existing_items:
            base_quantity = _q4(row.quantity)
            if base_quantity <= 0:
                continue
            await apply_stock_movement(
                self.session,
                product_id=row.product_id,
                movement_type="SALE_RETURN",
                quantity_delta=base_quantity,
                unit_cost=row.unit_cost,
                reference_type="sale",
                reference_id=sale.id,
                created_by=actor.id,
                document_no=sale.invoice_no,
                allow_negative=True,
            )
            await self.session.delete(row)
        await self.session.flush()

        # 2) Apply the new lines with the same rules as complete_sale.
        subtotal = Decimal("0.00")
        item_rows: list[SaleItem] = []
        for item in payload.items:
            product = products[item.product_id]
            quantity = item.quantity

            default_price = product.selling_price
            quantity = _q4(quantity)
            if quantity <= 0:
                raise ValidationError("Line quantity must be greater than zero", field_errors={"items": "Invalid quantity"})

            # Sold-by-area line: Height × Width (metres) becomes the billed m².
            height = item.height
            width = item.width
            area_m2 = None
            if (height is None) != (width is None):
                raise ValidationError(
                    "Height and width must be provided together",
                    field_errors={"items": "Height and width required"},
                )
            if height is not None and width is not None:
                area_m2 = _q4(Decimal(height) * Decimal(width))
                quantity = area_m2
                if quantity <= 0:
                    raise ValidationError("Line area must be greater than zero", field_errors={"items": "Invalid area"})

            if item.unit_price is None:
                # No client price → charge the product's selling price.
                unit_price = _to_sale_currency(default_price, payload.exchange_rate)
            else:
                unit_price = item.unit_price
            gross = (quantity * unit_price).quantize(TWO, rounding=ROUND_HALF_UP)
            line_total = gross

            provisional = SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                product_name=product.name,
                sku=product.sku,
                height=height,
                width=width,
                area_m2=area_m2,
                quantity=quantity,
                unit_price=unit_price,
                unit_cost=Decimal("0.00"),
                line_total=line_total,
            )
            self.session.add(provisional)
            await self.session.flush()
            balance = await _lock_balance(self.session, product.id)
            line_cost = _q2(balance.average_cost or product.cost_price)
            provisional.unit_cost = line_cost
            await self.session.flush()
            await apply_stock_movement(
                self.session,
                product_id=product.id,
                movement_type="SALE",
                quantity_delta=-quantity,
                unit_cost=line_cost,
                reference_type="sale",
                reference_id=sale.id,
                created_by=actor.id,
                document_no=sale.invoice_no,
                allow_negative=negative_ok,
            )
            item_rows.append(provisional)
            subtotal += gross

        delivery_price = _q2(payload.delivery_price)
        grand_total = subtotal + delivery_price

        sale.sale_date = payload.sale_date or sale.sale_date
        sale.note = payload.note
        sale.currency = payload.currency
        sale.exchange_rate = payload.exchange_rate
        sale.subtotal = _q2(subtotal)
        sale.delivery_price = delivery_price
        sale.grand_total = _q2(grand_total)

        # 3) Recalculate the outstanding customer debt from the new total.
        #    Recorded payments are immutable, so the already-paid amount stands.
        debt_result = await self.session.execute(
            select(CustomerDebt).where(CustomerDebt.sale_id == sale.id).with_for_update()
        )
        debt = debt_result.scalars().first()
        existing_paid = _q2(debt.paid_amount) if debt is not None else _q2(sale.paid_amount)
        paid_for_sale = max(Decimal("0.00"), min(existing_paid, sale.grand_total))
        debt_amount = sale.grand_total - paid_for_sale
        if debt_amount > 0 and customer.is_walk_in:
            raise ValidationError(
                "The walk-in customer cannot make a debt purchase",
                field_errors={"customer_id": "Select a registered customer"},
            )
        if debt is not None:
            debt.original_amount = sale.grand_total
            debt.paid_amount = paid_for_sale
            debt.remaining_amount = debt_amount
            debt.status = "PAID" if debt_amount == 0 else ("PARTIAL" if paid_for_sale > 0 else "UNPAID")
            # The edit rewrites the sale currency/rate; the debt must follow so
            # amounts and their normalization stay in one currency.
            debt.currency = sale.currency
            debt.exchange_rate = sale.exchange_rate
        elif debt_amount > 0:
            self.session.add(
                CustomerDebt(
                    customer_id=customer.id,
                    sale_id=sale.id,
                    invoice_no=sale.invoice_no,
                    original_amount=sale.grand_total,
                    paid_amount=paid_for_sale,
                    remaining_amount=debt_amount,
                    due_date=getattr(payload, "due_date", None),
                    status="UNPAID" if paid_for_sale == 0 else "PARTIAL",
                    currency=sale.currency,
                    exchange_rate=sale.exchange_rate,
                )
            )
        sale.paid_amount = paid_for_sale
        sale.debt_amount = debt_amount
        sale.payment_status = "PAID" if debt_amount == 0 else ("PARTIAL" if paid_for_sale > 0 else "UNPAID")

        await record_audit(
            self.session,
            action="sale_update",
            module="pos",
            user_id=actor.id,
            entity_type="sale",
            entity_id=sale.id,
            new_values={"invoice_no": sale.invoice_no, "grand_total": str(sale.grand_total)},
        )
        await self.session.commit()
        return sale_to_out(sale, customer_name=customer.name, items=item_rows)

    async def _resolve_customer(self, payload) -> Customer:
        if payload.customer_id is None:
            walk_in = await get_walk_in_customer(self.session)
            if walk_in is None:
                raise ValidationError("Walk-in customer is not seeded", field_errors={"customer_id": "Missing walk-in customer"})
            return walk_in
        customer = await self.session.get(Customer, payload.customer_id)
        if customer is None:
            raise NotFoundError("Customer not found")
        return customer

    async def _create_payment(
        self,
        *,
        payment_no,
        sale_id,
        customer_id,
        payment_type,
        payment_method,
        amount,
        reference_no,
        actor,
        customer_debt_id=None,
    ) -> Payment:
        payment = Payment(
            payment_no=payment_no,
            sale_id=sale_id,
            customer_id=customer_id,
            customer_debt_id=customer_debt_id,
            payment_type=payment_type,
            payment_method=payment_method,
            amount=_q2(amount),
            reference_no=reference_no,
            created_by=actor.id,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    # --------------------------------------------------------------- receipt

    async def build_receipt(self, sale: Sale) -> dict:
        """Print-ready bilingual invoice payload (the frontend renders HTML)."""
        from zoneinfo import ZoneInfo

        from app.modules.administration import get_setting_value

        shop_name = await get_setting_value(self.session, "shop", "shop_name", "MJ Printing")
        shop_address = await get_setting_value(self.session, "shop", "address", "")
        shop_phone = await get_setting_value(self.session, "shop", "phone", "")
        logo = await get_setting_value(self.session, "invoice", "logo", "")
        tz_name = await get_setting_value(self.session, "system", "timezone", "UTC")
        try:
            tz = ZoneInfo(str(tz_name) or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        # Invoice presentation settings (paper size, exchange-rate display,
        # footer fallback) — the frontend reads these to render the paper.
        paper_size = await get_setting_value(self.session, "invoice", "paper_size", "A4")
        show_exchange_rate = bool(
            await get_setting_value(self.session, "invoice", "show_exchange_rate", False)
        )
        footer = await get_setting_value(self.session, "invoice", "footer", "")
        receipt_footer = await get_setting_value(self.session, "pos", "receipt_footer", "")
        receipt_footer = footer or receipt_footer
        sale_date = sale.sale_date if sale.sale_date.tzinfo else sale.sale_date.replace(tzinfo=timezone.utc)

        cashier = None
        customer_name = None
        cashier_result = await self.session.execute(
            select(User.full_name).where(User.id == sale.cashier_id)
        )
        cashier = cashier_result.scalar_one_or_none()
        customer_result = await self.session.execute(
            select(Customer.name, Customer.phone, Customer.address).where(Customer.id == sale.customer_id)
        )
        customer_row = customer_result.one_or_none()
        customer_name = customer_row.name if customer_row else None
        customer_phone = customer_row.phone if customer_row else None
        customer_address = customer_row.address if customer_row else None

        debt_result = await self.session.execute(
            select(func.coalesce(func.sum(CustomerDebt.remaining_amount), 0)).where(
                CustomerDebt.sale_id == sale.id
            )
        )
        debt_remaining = Decimal(debt_result.scalar_one())

        method_result = await self.session.execute(
            select(Payment.payment_method)
            .where(Payment.sale_id == sale.id, Payment.payment_type == "SALE_PAYMENT")
            .order_by(Payment.created_at.desc(), Payment.id)
            .limit(1)
        )
        payment_method = method_result.scalar_one_or_none() or (
            "CUSTOMER_DEBT" if debt_remaining > 0 else "UNPAID"
        )

        return {
            "shop": {
                "name": shop_name,
                "address": shop_address,
                "phone": shop_phone,
                "logo": logo or None,
            },
            "invoice_no": sale.invoice_no,
            "sale_date": sale_date.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S"),
            "cashier": cashier,
            "customer": customer_name,
            # Customer contact snapshot (only when the customer has one).
            "customer_phone": customer_phone or None,
            "customerPhone": customer_phone or None,
            "customer_address": customer_address or None,
            "customerAddress": customer_address or None,
            # Document currency: the whole receipt renders in THIS currency.
            "currency": sale.currency,
            "exchange_rate": str(sale.exchange_rate),
            "exchangeRate": str(sale.exchange_rate),
            # Presentation settings (backend values are authoritative).
            "paper_size": paper_size,
            "paperSize": paper_size,
            "show_exchange_rate": show_exchange_rate,
            "showExchangeRate": show_exchange_rate,
            "footer": receipt_footer or None,
            "items": [
                {
                    "id": item.id,
                    "name": item.product_name,
                    "sku": item.sku,
                    "height": None if item.height is None else str(item.height),
                    "width": None if item.width is None else str(item.width),
                    "area_m2": None if item.area_m2 is None else str(item.area_m2),
                    "quantity": str(item.quantity),
                    "qty": str(item.quantity),
                    "unit_price": str(item.unit_price),
                    "line_total": str(item.line_total),
                }
                for item in sale.items
            ],
            "subtotal": str(sale.subtotal),
            "delivery_price": str(sale.delivery_price),
            "deliveryPrice": str(sale.delivery_price),
            "grand_total": str(sale.grand_total),
            "paid": str(sale.paid_amount),
            "amount_received": str(sale.paid_amount),
            "amountReceived": str(sale.paid_amount),
            "debt": str(sale.debt_amount),
            "change": str(max(Decimal("0"), sale.paid_amount - (sale.grand_total - sale.debt_amount)))
            if sale.debt_amount == 0
            else "0.00",
            "debt_remaining": str(debt_remaining),
            "payment_method": payment_method,
            "payment_status": sale.payment_status,
            "note": sale.note,
            "receipt_ready_for_print": True,
        }

    # ------------------------------------------------------------------ read

    async def get_sale(self, sale_id: uuid.UUID) -> Sale:
        result = await self.session.execute(select(Sale).where(Sale.id == sale_id))
        sale = result.scalar_one_or_none()
        if sale is None:
            raise NotFoundError("Sale not found")
        return sale

    async def get_sale_out(self, sale_id: uuid.UUID) -> SaleOut:
        """GET path detail with the customer name resolved (the SPA edit screen
        shows the buyer without depending on the cached options list)."""
        sale = await self.get_sale(sale_id)
        customer_name: str | None = None
        if sale.customer_id is not None:
            from app.modules.customers.models import Customer

            result = await self.session.execute(
                select(Customer.name).where(Customer.id == sale.customer_id)
            )
            customer_name = result.scalar_one_or_none()
        return sale_to_out(sale, customer_name=customer_name)

    async def list_sales(self, *, q, customer_id, start, end, page, limit):
        from app.shared.pagination.params import parse_date_range

        stmt = select(Sale)
        count_stmt = select(func.count()).select_from(Sale)
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(Sale.invoice_no.ilike(pattern))
            count_stmt = count_stmt.where(Sale.invoice_no.ilike(pattern))
        if customer_id is not None:
            stmt = stmt.where(Sale.customer_id == customer_id)
            count_stmt = count_stmt.where(Sale.customer_id == customer_id)
        start_at, end_at = parse_date_range(start, end)
        if start_at is not None:
            stmt = stmt.where(Sale.sale_date >= start_at)
            count_stmt = count_stmt.where(Sale.sale_date >= start_at)
        if end_at is not None:
            stmt = stmt.where(Sale.sale_date <= end_at)
            count_stmt = count_stmt.where(Sale.sale_date <= end_at)
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = await self.session.execute(
            stmt.order_by(Sale.sale_date.desc()).offset((page - 1) * limit).limit(limit)
        )
        return list(rows.scalars().all()), int(total)

    # ---------------------------------------------------------------- return

    async def return_sale(self, sale_id: uuid.UUID, payload, *, actor: User) -> SaleReturnOut:
        # Lock the sale row so concurrent returns (and sale edits) serialize;
        # without it two requests could both read the same returned_quantity
        # and over-return stock/refunds.
        result = await self.session.execute(
            select(Sale).where(Sale.id == sale_id).with_for_update()
        )
        sale = result.scalar_one_or_none()
        if sale is None:
            raise NotFoundError("Sale not found")
        if sale.sale_status not in ("COMPLETED", "PARTIAL_RETURN"):
            raise ConflictError("This sale can no longer be returned")

        items_by_id: dict[uuid.UUID, SaleItem] = {item.id: item for item in sale.items}
        # Sum requested quantities per line first: duplicate sale_item_id rows
        # must be validated against the remaining quantity as a whole, never
        # each independently.
        requested: dict[uuid.UUID, Decimal] = {}
        for return_item in payload.items:
            sale_item = items_by_id.get(return_item.sale_item_id)
            if sale_item is None:
                raise NotFoundError("Sale item not found on this sale")
            requested[return_item.sale_item_id] = (
                requested.get(return_item.sale_item_id, Decimal("0")) + return_item.quantity
            )
        for item_id, total_quantity in requested.items():
            sale_item = items_by_id[item_id]
            remaining = sale_item.quantity - sale_item.returned_quantity
            if total_quantity > remaining:
                raise ValidationError(
                    f"Cannot return more than the remaining quantity ({remaining})",
                    field_errors={"items": "Return quantity exceeds remaining"},
                )

        return_no = await allocate_document_number(self.session, "SALE_RETURN")
        sale_return = SaleReturn(
            return_no=return_no,
            sale_id=sale.id,
            return_date=payload.return_date or datetime.now(timezone.utc),
            refund_amount=Decimal("0.00"),
            reason=payload.reason,
            created_by=actor.id,
        )
        self.session.add(sale_return)
        await self.session.flush()

        refund_total = Decimal("0.00")
        out_items: list[SaleReturnItem] = []
        for return_item in payload.items:
            sale_item = items_by_id[return_item.sale_item_id]
            refund = _q2(sale_item.line_total * return_item.quantity / sale_item.quantity)
            row = SaleReturnItem(
                sale_return_id=sale_return.id,
                sale_item_id=sale_item.id,
                product_id=sale_item.product_id,
                quantity=return_item.quantity,
                refund_amount=refund,
                restock=return_item.restock,
            )
            out_items.append(row)
            self.session.add(row)
            sale_item.returned_quantity = sale_item.returned_quantity + return_item.quantity
            if return_item.restock:
                base_return = _q4(Decimal(return_item.quantity))
                await apply_stock_movement(
                    self.session,
                    product_id=sale_item.product_id,
                    movement_type="SALE_RETURN",
                    quantity_delta=base_return,
                    unit_cost=sale_item.unit_cost,
                    reference_type="sale_return",
                    reference_id=sale_return.id,
                    created_by=actor.id,
                    document_no=return_no,
                    note=payload.reason,
                )
            refund_total += refund
        sale_return.refund_amount = _q2(refund_total)

        # A returned sale reduces what the customer still owes.
        debt_result = await self.session.execute(
            select(CustomerDebt).where(CustomerDebt.sale_id == sale.id).with_for_update()
        )
        debt = debt_result.scalar_one_or_none()
        if debt is not None and debt.remaining_amount > 0:
            reduction = min(sale_return.refund_amount, debt.remaining_amount)
            debt.remaining_amount = debt.remaining_amount - reduction
            debt.paid_amount = debt.original_amount - debt.remaining_amount
            debt.status = "PAID" if debt.remaining_amount == 0 else "PARTIAL"

        fully_returned = all(
            item.returned_quantity >= item.quantity for item in sale.items
        )
        sale.sale_status = "RETURNED" if fully_returned else "PARTIAL_RETURN"

        await record_audit(
            self.session,
            action="sale_return",
            module="pos",
            user_id=actor.id,
            entity_type="sale_return",
            entity_id=sale_return.id,
            new_values={
                "return_no": return_no,
                "invoice_no": sale.invoice_no,
                "refund_amount": str(sale_return.refund_amount),
            },
        )
        await self.session.commit()

        return SaleReturnOut(
            id=sale_return.id,
            return_no=sale_return.return_no,
            sale_id=sale.id,
            invoice_no=sale.invoice_no,
            return_date=sale_return.return_date,
            refund_amount=sale_return.refund_amount,
            reason=sale_return.reason,
            items=[
                SaleReturnItemOut(
                    id=row.id,
                    sale_item_id=row.sale_item_id,
                    product_id=row.product_id,
                    product_name=items_by_id[row.sale_item_id].product_name,
                    quantity=row.quantity,
                    refund_amount=row.refund_amount,
                    restock=row.restock,
                )
                for row in out_items
            ],
        )
