"""Product and stock balance models — spec section 4.2."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_name", "name"),
        Index("ix_products_category_id", "category_id"),
        Index("ix_products_brand_id", "brand_id"),
        Index("ix_products_uom_id", "uom_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Legacy internal code: optional (barcode is the operational identifier);
    # UNIQUE retained so any stored value stays distinct.
    sku: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    # Operational identifier: unique, required, POS barcode lookup.
    barcode: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    # UOM is required (spec section 2.1.5); products always reference the live record.
    uom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="RESTRICT"), nullable=False
    )
    cost_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    selling_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    minimum_stock: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    expiry_tracking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Costing option: when True, outbound movements (sales, damage, expiry,
    # adjustment out) are costed FIFO — the oldest remaining stock-in lots —
    # instead of the weighted average cost.
    fifo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Batch tracking: when True, incoming stock MUST be assigned a batch_no
    # (spec: batch/lot management). Unbatched products stay the legacy path.
    track_batch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Pricing rows (spec 4.2 / §2.1.3 products): [{uom_id, uom_symbol,
    # convert_uom_id, convert_uom_symbol, factor_to_base, sale_price,
    # is_default_sale, cost_price?}]. Validated by the product service.
    uom_conversions: Mapped[list | None] = mapped_column(JSONB(astext_type=Text()), nullable=True, default=list)
    image_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    category_ref = relationship("Category", lazy="selectin")
    brand_ref = relationship("Brand", lazy="selectin")
    uom_ref = relationship("UOM", lazy="selectin")
    balance: Mapped["StockBalance | None"] = relationship(
        back_populates="product_ref", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )
    sale_prices: Mapped[list["ProductSalePrice"]] = relationship(
        back_populates="product_ref", lazy="selectin", cascade="all, delete-orphan"
    )


class StockBalance(Base):
    """Materialized current stock; updated only inside stock transactions."""

    __tablename__ = "stock_balances"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    average_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    product_ref: Mapped[Product] = relationship(back_populates="balance")


class BatchStockBalance(Base):
    """Per-(product, batch_no) remaining base quantity + cost + lifecycle.

    The authoritative batch state (spec: batch = physical inventory, expiry,
    cost). Written only by the canonical stock-mutation service under row
    lock; the product's stock_balances row stays the materialized total.
    """

    __tablename__ = "batch_stock_balances"
    __table_args__ = (
        # Batch identity = product + batch_no; expiry_date is a recorded
        # ATTRIBUTE of the lot (stamped from the purchase), not part of its
        # identity — operations reference a batch by batch_no only.
        UniqueConstraint("product_id", "batch_no", name="uq_batch_stock_balances"),
        Index("ix_batch_stock_balances_product_id", "product_id"),
        Index("ix_batch_stock_balances_product_expiry", "product_id", "expiry_date"),
        Index("ix_batch_stock_balances_expiry_date", "expiry_date"),
        # Ledger integrity (spec: batch quantities never negative, never
        # exceed what was received into the lot).
        CheckConstraint("remaining_quantity >= 0", name="ck_batch_remaining_nonneg"),
        CheckConstraint("received_quantity >= remaining_quantity", name="ck_batch_received_gte_remaining"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    batch_no: Mapped[str] = mapped_column(String(100), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    remaining_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    # Lifecycle: ACTIVE | DEPLETED | EXPIRED (maintained by the mutation paths).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    # Traceable purchase cost per BASE unit of the lot (latest purchase).
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0.000000"))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    document_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductSalePrice(Base):
    """Versioned POS sale price (spec 4.2 product_sale_prices).

    Exactly one row per product is POS-active (partial unique index); the
    active row's sale_price is always copied onto products.selling_price in
    the same transaction, so POS and the Stock list can never diverge.
    Cost history is NOT stored here — it is derived from Stock In lots.
    """

    __tablename__ = "product_sale_prices"
    __table_args__ = (
        UniqueConstraint("product_id", "version", name="uq_product_sale_prices_product_version"),
        Index(
            "uq_product_sale_prices_one_active",
            "product_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_product_sale_prices_product_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    sale_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    product_ref: Mapped[Product] = relationship(back_populates="sale_prices")


class StockTransaction(Base):
    """Header for stock in / adjustment / damage / expire operations."""

    __tablename__ = "stock_transactions"
    __table_args__ = (Index("ix_stock_transactions_created_at", "transaction_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Purchase header adjustments (Stock In = purchase): discount is
    # subtracted from the line subtotal, tax is added afterwards.
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    # Document currency: every amount on this document is in THIS currency
    # (never mixed). exchange_rate = KHR per 1 USD (1 for USD documents).
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD", server_default="USD")
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, default=Decimal("1"), server_default="1"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CONFIRMED")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["StockTransactionItem"]] = relationship(
        back_populates="transaction_ref", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseReturn(Base):
    """Immutable supplier-return document against a confirmed Stock In
    (spec 4.2 purchase_returns). Never a standalone page — created from the
    Purchase Report / Stock In history via POST /stock/in/{id}/return."""

    __tablename__ = "purchase_returns"
    __table_args__ = (Index("ix_purchase_returns_stock_transaction_id", "stock_transaction_id"),
                      Index("ix_purchase_returns_supplier_id", "supplier_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    return_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    stock_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    return_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    debt_reduction: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )
    credit_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list["PurchaseReturnItem"]] = relationship(
        back_populates="return_ref", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseReturnItem(Base):
    """One returned stock-in line; quantities are in the product base UOM."""

    __tablename__ = "purchase_return_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    purchase_return_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_returns.id", ondelete="CASCADE"), nullable=False
    )
    stock_transaction_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_transaction_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    line_refund: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    return_ref: Mapped[PurchaseReturn] = relationship(back_populates="items")


class StockTransactionItem(Base):
    __tablename__ = "stock_transaction_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_transactions.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    system_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    actual_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    batch_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Line UOM symbol snapshot (the selected Pricing UOM for Stock In lines).
    uom_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Entered UOM of the operator on outbound lines (Damage / Expiry /
    # Purchase Return): entered_quantity = quantity_base Ã· factor. Ledger
    # and batch quantities stay in the base UOM (display only).
    entered_uom_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entered_uom_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entered_factor_to_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    entered_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    # Cumulative returned-to-supplier qty (base UOM) across purchase returns.
    returned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    transaction_ref: Mapped[StockTransaction] = relationship(back_populates="items")
    product_ref: Mapped[Product] = relationship(lazy="selectin")


class StockMovement(Base):
    """Immutable, append-only record of every stock change."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_product_id", "product_id"),
        Index("ix_stock_movements_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    batch_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Batch lot link (single-batch movements only; multi-batch outflows such
    # as a POS line drawing from several lots stay NULL — the per-batch
    # detail lives in the allocation/ledger rows).
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batch_stock_balances.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # Line UOM symbol snapshot (display only; quantities stay in base UOM).
    uom_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product_ref: Mapped[Product] = relationship(lazy="selectin")
