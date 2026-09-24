from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

PAYMENT_METHODS = {"CASH", "BANK_QR", "CUSTOMER_DEBT"}
TENDER_METHODS = {"CASH", "BANK_QR"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------- search


class POSProductOut(BaseModel):
    id: UUID
    sku: str | None
    name: str
    category_id: UUID | None
    category_name: str | None = None
    selling_price: Decimal
    quantity: Decimal = Decimal("0")
    image_object_key: str | None
    image_url: str | None = None
    status: str


# --------------------------------------------------------------------- sale


class SaleItemRequest(BaseModel):
    """One POS cart line (snake_case and camelCase accepted).

    unit_price defaults to the product's selling price
    (products.selling_price).
    """

    model_config = ConfigDict(populate_by_name=True)

    product_id: UUID = Field(validation_alias=AliasChoices("product_id", "productId"))
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("unit_price", "unitPrice"),
    )
    # Sold-by-area lines: when both are given, quantity = height × width (m²).
    height: Decimal | None = Field(default=None, gt=0)
    width: Decimal | None = Field(default=None, gt=0)


class SaleCreateRequest(BaseModel):
    """PosCompleteSaleInput — camelCase keys from the frontend, snake_case
    accepted too.

    `amount_received` / paidAmount is payment for THIS sale only (grand_total =
    subtotal + delivery). `deposit` is the separate budget applied
    to selected prior customer debts via included_debt_ids and never inflates
    the current sale total.

    Canonical payment methods: CASH | BANK_QR | CUSTOMER_DEBT. The UI's
    display labels map one-to-one: Cash→CASH, Card / Mobile Payment /
    Bank Transfer→BANK_QR (cashless tender), Credit→CUSTOMER_DEBT."""

    model_config = ConfigDict(populate_by_name=True)

    customer_id: UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("customer_id", "customerId"),
    )
    sale_date: datetime | None = None
    payment_method: str = Field(
        default="CASH",
        validation_alias=AliasChoices("payment_method", "paymentMethod"),
    )
    amount_received: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        validation_alias=AliasChoices("amount_received", "paidAmount", "paid_amount"),
    )
    delivery_price: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        validation_alias=AliasChoices("delivery_price", "deliveryPrice"),
    )
    # Open customer-debt rows settled in this transaction from `deposit`
    # (separate from amount_received / current-sale payment).
    included_debt_ids: list[UUID] = Field(
        default_factory=list,
        validation_alias=AliasChoices("included_debt_ids", "includedDebtIds"),
    )
    # Budget for settling included prior debts (not part of sale grand_total).
    deposit: Decimal = Field(default=Decimal("0"), ge=0)
    deposit_method: str | None = Field(default=None, pattern="^(CASH|BANK_QR)$")
    reference_no: str | None = Field(default=None, max_length=100)
    note: str | None = None
    due_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices("due_date", "dueDate"),
    )
    # Document currency: every amount on this sale (lines, delivery,
    # paid, debt) is in THIS currency. exchange_rate = KHR per 1 USD.
    currency: str = Field(default="USD", pattern="^(USD|KHR)$")
    exchange_rate: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        validation_alias=AliasChoices("exchange_rate", "exchangeRate"),
    )
    items: list[SaleItemRequest] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_request(self):
        if self.payment_method not in PAYMENT_METHODS:
            raise ValueError("payment_method must be CASH, BANK_QR or CUSTOMER_DEBT")
        if self.payment_method == "CUSTOMER_DEBT" and self.deposit_method is None:
            self.deposit_method = "CASH"
        if self.payment_method in TENDER_METHODS and self.amount_received <= 0:
            raise ValueError("amount_received must be greater than zero")
        return self


class SaleUpdateRequest(BaseModel):
    """PATCH /pos/sales/{id} — edit a completed sale (no returns).

    Items/quantities/prices/delivery are re-applied; the original
    stock is reversed before the new lines are
    applied. The customer and any recorded payments stay untouched — the
    outstanding customer debt is recalculated from the new grand total.
    """

    model_config = ConfigDict(populate_by_name=True)

    sale_date: datetime | None = None
    delivery_price: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        validation_alias=AliasChoices("delivery_price", "deliveryPrice"),
    )
    note: str | None = None
    currency: str = Field(default="USD", pattern="^(USD|KHR)$")
    exchange_rate: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        validation_alias=AliasChoices("exchange_rate", "exchangeRate"),
    )
    items: list[SaleItemRequest] = Field(min_length=1)


class SaleItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_id: UUID
    product_name: str
    sku: str | None
    height: Decimal | None = None
    width: Decimal | None = None
    area_m2: Decimal | None = None
    quantity: Decimal
    unit_price: Decimal
    unit_cost: Decimal
    line_total: Decimal
    returned_quantity: Decimal


class SaleOut(BaseModel):
    id: UUID
    invoice_no: str
    customer_id: UUID
    customer_name: str | None = None
    sale_date: datetime
    subtotal: Decimal
    delivery_price: Decimal = Decimal("0")
    deliveryPrice: Decimal = Decimal("0")
    grand_total: Decimal
    paid_amount: Decimal
    debt_amount: Decimal
    payment_status: str
    sale_status: str
    cashier_id: UUID
    note: str | None
    change_amount: Decimal = Decimal("0")
    currency: str = "USD"
    exchange_rate: Decimal = Decimal("1")
    items: list[SaleItemOut]


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_no: str
    payment_type: str
    payment_method: str
    amount: Decimal
    reference_no: str | None
    customer_debt_id: UUID | None = None
    supplier_debt_id: UUID | None = None
    note: str | None = None
    created_at: datetime


# ------------------------------------------------------------------- return


class SaleReturnItemRequest(BaseModel):
    """One return line; camelCase keys accepted (UI adapter contract)."""

    model_config = ConfigDict(populate_by_name=True)

    sale_item_id: UUID = Field(validation_alias=AliasChoices("sale_item_id", "saleItemId"))
    quantity: Decimal = Field(gt=0)
    restock: bool = True


class SaleReturnRequest(BaseModel):
    """POST /pos/sales/{id}/return body. `items` is canonical; `lines` is an
    accepted alias so both API dialects work (spec 2.1.7)."""

    reason: str = Field(min_length=1, max_length=1000)
    items: list[SaleReturnItemRequest] = Field(
        min_length=1, validation_alias=AliasChoices("items", "lines")
    )
    return_date: datetime | None = None


class SaleReturnItemOut(BaseModel):
    id: UUID
    sale_item_id: UUID
    product_id: UUID
    product_name: str | None = None
    quantity: Decimal
    refund_amount: Decimal
    restock: bool


class SaleReturnOut(BaseModel):
    id: UUID
    return_no: str
    sale_id: UUID
    invoice_no: str | None = None
    return_date: datetime
    refund_amount: Decimal
    reason: str
    items: list[SaleReturnItemOut]


# -------------------------------------------------------------------- debts


class DebtPaymentRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_method: str = Field(pattern="^(CASH|BANK_QR)$")
    reference_no: str | None = Field(default=None, max_length=100)
    note: str | None = None


class CustomerDebtOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    sale_id: UUID
    invoice_no: str
    original_amount: Decimal
    paid_amount: Decimal
    remaining_amount: Decimal
    due_date: date | None
    status: str
    currency: str = "USD"
    exchange_rate: Decimal = Decimal("1")
    created_at: datetime
