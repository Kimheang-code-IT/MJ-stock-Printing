from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

class ProductCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Optional internal product code.
    sku: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    category_id: UUID
    brand_id: UUID | None = None
    supplier_id: UUID | None = Field(
        default=None, validation_alias=AliasChoices("supplier_id", "supplierId")
    )
    cost_price: Decimal = Field(default=Decimal("0.00"), ge=0)
    selling_price: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("selling_price", "salePrice"),
    )
    minimum_stock: Decimal = Field(default=Decimal("0"), ge=0)
    image_object_key: str | None = Field(default=None, max_length=500)
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|INACTIVE)$")
    note: str | None = None

    @field_validator("sku", "name")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

class ProductUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sku: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: UUID | None = None
    brand_id: UUID | None = None
    supplier_id: UUID | None = Field(
        default=None, validation_alias=AliasChoices("supplier_id", "supplierId")
    )
    cost_price: Decimal | None = Field(default=None, ge=0)
    # The UI sends salePrice; POS charges this price directly.
    selling_price: Decimal | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("selling_price", "salePrice"),
    )
    minimum_stock: Decimal | None = Field(default=None, ge=0)
    image_object_key: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE)$")
    note: str | None = None

    @field_validator("sku", "name")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


# ---------------------------------------------------------------- stock operations


class StockInItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)
    # Sold-by-area purchase line: when both are given the received quantity
    # becomes height x width (m²), mirroring the POS sale line.
    height: Decimal | None = Field(default=None, gt=0)
    width: Decimal | None = Field(default=None, gt=0)

class StockInRequest(BaseModel):
    """POST /stock/in — Stock In = purchase (spec 2.1.x).

    payment_method is the canonical POS tender vocabulary (CASH | BANK_QR);
    it labels the payment row recorded when paid_amount > 0."""

    model_config = ConfigDict(populate_by_name=True)

    supplier_id: UUID | None = Field(
        default=None, validation_alias=AliasChoices("supplier_id", "supplierId")
    )
    transaction_date: datetime | None = None
    reference_no: str | None = Field(default=None, max_length=100)
    note: str | None = None
    paid_amount: Decimal = Field(
        default=Decimal("0"), ge=0, validation_alias=AliasChoices("paid_amount", "paidAmount")
    )
    payment_method: str = Field(default="CASH", validation_alias=AliasChoices("payment_method", "paymentMethod"))
    # Document-level adjustment (purchase form footer): tax is added to the
    # line subtotal.
    tax_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        validation_alias=AliasChoices("tax_amount", "taxAmount"),
    )
    # Document currency: every amount (lines, tax, paid, debt) is
    # in THIS currency. exchange_rate = KHR per 1 USD (1 for USD documents).
    currency: str = Field(default="USD", pattern="^(USD|KHR)$")
    exchange_rate: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        validation_alias=AliasChoices("exchange_rate", "exchangeRate"),
    )
    items: list[StockInItem] = Field(min_length=1, validation_alias=AliasChoices("items", "lines"))

class StockInUpdateRequest(BaseModel):
    """PATCH /stock/in/{id} — edit a confirmed Stock In (no purchase returns).

    The original received quantities are reversed (compensating
    PURCHASE_RETURN movement) before the new lines are received. The supplier
    and immutable payments stay; the outstanding supplier debt is recalculated.
    """

    model_config = ConfigDict(populate_by_name=True)

    transaction_date: datetime | None = None
    reference_no: str | None = Field(default=None, max_length=100)
    note: str | None = None
    tax_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        validation_alias=AliasChoices("tax_amount", "taxAmount"),
    )
    currency: str = Field(default="USD", pattern="^(USD|KHR)$")
    exchange_rate: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        validation_alias=AliasChoices("exchange_rate", "exchangeRate"),
    )
    items: list[StockInItem] = Field(min_length=1, validation_alias=AliasChoices("items", "lines"))

class AdjustmentItem(BaseModel):
    product_id: UUID
    system_quantity: Decimal | None = Field(default=None, ge=0)
    actual_quantity: Decimal = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)
    note: str | None = None

class StockAdjustmentRequest(BaseModel):
    transaction_date: datetime | None = None
    reference_no: str | None = Field(default=None, max_length=100)
    note: str | None = None
    items: list[AdjustmentItem] = Field(min_length=1)

class DamageItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: UUID
    quantity: Decimal = Field(gt=0)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)
    note: str | None = None

class StockDamageRequest(BaseModel):
    transaction_date: datetime | None = None
    reference_no: str | None = Field(default=None, max_length=100)
    note: str | None = None
    items: list[DamageItem] = Field(min_length=1)

class PurchaseReturnItemRequest(BaseModel):
    """One line of POST /stock/in/{id}/return (spec 2.1.x Return to supplier)."""

    model_config = ConfigDict(populate_by_name=True)

    stock_transaction_item_id: UUID = Field(
        validation_alias=AliasChoices("stock_transaction_item_id", "stockTransactionItemId")
    )
    quantity: Decimal = Field(gt=0)

class PurchaseReturnRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reason: str = Field(min_length=1, max_length=1000)
    lines: list[PurchaseReturnItemRequest] = Field(
        min_length=1, validation_alias=AliasChoices("lines", "items")
    )
    return_date: datetime | None = None

class PurchaseReturnItemOut(BaseModel):
    id: UUID
    stock_transaction_item_id: UUID
    product_id: UUID
    product_name: str | None = None
    quantity: Decimal
    unit_cost: Decimal
    line_refund: Decimal

class PurchaseReturnOut(BaseModel):
    id: UUID
    return_no: str
    stock_transaction_id: UUID
    document_no: str | None = None
    supplier_id: UUID | None = None
    return_date: datetime
    refund_amount: Decimal
    debt_reduction: Decimal = Decimal("0.00")
    credit_amount: Decimal = Decimal("0.00")
    reason: str
    items: list[PurchaseReturnItemOut]

class OperationItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str | None = None
    sku: str | None = None
    quantity: Decimal
    unit_cost: Decimal
    height: Decimal | None = None
    width: Decimal | None = None
    area_m2: Decimal | None = None
    system_quantity: Decimal | None
    actual_quantity: Decimal | None
    reason: str | None
    line_total: Decimal

class StockOperationOut(BaseModel):
    id: UUID
    document_no: str
    transaction_type: str
    supplier_id: UUID | None
    transaction_date: datetime
    reference_no: str | None
    note: str | None
    status: str
    total_amount: Decimal
    paid_amount: Decimal
    tax_amount: Decimal = Decimal("0.00")
    currency: str = "USD"
    exchange_rate: Decimal = Decimal("1")
    debt_created: bool = False
    debt_id: UUID | None = None
    items: list[OperationItemOut]

class QuickStockOperationRequest(BaseModel):
    """Single-product quick operation from the Stock list
    (`type`: stock_in | adjustment | damage)."""

    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(default="stock_in", pattern="^(stock_in|adjustment|damage)$")
    product_id: UUID = Field(validation_alias=AliasChoices("product_id", "productId"))
    quantity: Decimal
    note: str | None = Field(default=None, max_length=1000)
    transaction_date: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("transaction_date", "transactionDate", "date"),
    )
    unit_cost: Decimal | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("unit_cost", "unitCost"),
    )

class MovementOut(BaseModel):
    """GET /stock/movements row (Stock Movements page).

    ``qty_in``/``qty_out`` are unsigned convenience projections of the signed
    ``quantity_delta``; ``balance_before``/``balance_after`` are derived from
    the immutable movement ledger (never persisted).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str | None = None
    sku: str | None = None
    movement_type: str
    quantity_delta: Decimal
    qty_in: Decimal = Decimal("0")
    qty_out: Decimal = Decimal("0")
    balance_before: Decimal = Decimal("0")
    balance_after: Decimal = Decimal("0")
    unit_cost: Decimal
    reference_type: str
    reference_id: UUID
    document_no: str | None
    source_reference: str | None = None
    note: str | None
    user: str | None = None
    created_by: UUID | None = None
    created_at: datetime
