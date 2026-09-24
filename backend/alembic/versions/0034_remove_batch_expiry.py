"""Remove the batch / expiry feature end-to-end.

Revision ID: 0034_remove_batch_expiry
Revises: 0033_remove_pricing_barcode
Create Date: 2026-09-24

The system no longer tracks product batches, batch numbers, FEFO allocation,
or expiry dates. Stock is tracked only by the materialized `stock_balances`
row (quantity + average cost) and the immutable `stock_movements` ledger.

Upgrade (data loss, irreversible):
- drop `sale_item_batches` and `batch_stock_balances`;
- drop `telegram_expiry_alert_state`;
- drop `stock_movements.batch_id` (and its index), `.batch_no`, `.expiry_date`;
- drop `stock_transaction_items.batch_no`, `.expiry_date`;
- drop `products.track_batch`, `products.expiry_tracking`, `products.fifo`.

Downgrade recreates them in their pre-0034 shape (empty).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034_remove_batch_expiry"
down_revision = "0033_remove_pricing_barcode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Child tables first, then the batch ledger they reference.
    op.execute("DROP TABLE IF EXISTS sale_item_batches CASCADE")
    op.execute("DROP TABLE IF EXISTS batch_stock_balances CASCADE")
    op.execute("DROP TABLE IF EXISTS telegram_expiry_alert_state CASCADE")

    # Movement batch/expiry traceability.
    op.execute("DROP INDEX IF EXISTS ix_stock_movements_batch_id")
    op.execute("ALTER TABLE stock_movements DROP COLUMN IF EXISTS batch_id")
    op.execute("ALTER TABLE stock_movements DROP COLUMN IF EXISTS batch_no")
    op.execute("ALTER TABLE stock_movements DROP COLUMN IF EXISTS expiry_date")

    # Stock-in line batch/expiry.
    op.execute("ALTER TABLE stock_transaction_items DROP COLUMN IF EXISTS batch_no")
    op.execute("ALTER TABLE stock_transaction_items DROP COLUMN IF EXISTS expiry_date")

    # Product batch/expiry/FIFO flags.
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS track_batch")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS expiry_tracking")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS fifo")


def downgrade() -> None:
    # ---- products flags --------------------------------------------------
    op.add_column(
        "products",
        sa.Column("expiry_tracking", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "products",
        sa.Column("fifo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "products",
        sa.Column("track_batch", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # ---- stock_transaction_items batch/expiry ----------------------------
    op.add_column("stock_transaction_items", sa.Column("batch_no", sa.String(100), nullable=True))
    op.add_column("stock_transaction_items", sa.Column("expiry_date", sa.Date(), nullable=True))

    # ---- batch_stock_balances (pre-0034 shape) ---------------------------
    op.create_table(
        "batch_stock_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("batch_no", sa.String(100), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("received_quantity", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("remaining_quantity", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("unit_cost", sa.Numeric(18, 6), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "supplier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppliers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("document_no", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("product_id", "batch_no", name="uq_batch_stock_balances"),
        sa.CheckConstraint("remaining_quantity >= 0", name="ck_batch_remaining_nonneg"),
        sa.CheckConstraint("received_quantity >= remaining_quantity", name="ck_batch_received_gte_remaining"),
    )
    op.create_index("ix_batch_stock_balances_product_id", "batch_stock_balances", ["product_id"])
    op.create_index(
        "ix_batch_stock_balances_product_expiry",
        "batch_stock_balances",
        ["product_id", "expiry_date"],
    )
    op.create_index("ix_batch_stock_balances_expiry_date", "batch_stock_balances", ["expiry_date"])

    # ---- stock_movements batch/expiry ------------------------------------
    op.add_column("stock_movements", sa.Column("batch_no", sa.String(100), nullable=True))
    op.add_column("stock_movements", sa.Column("expiry_date", sa.Date(), nullable=True))
    op.add_column(
        "stock_movements",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_stock_movements_batch_id",
        "stock_movements",
        "batch_stock_balances",
        ["batch_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_stock_movements_batch_id", "stock_movements", ["batch_id"])

    # ---- sale_item_batches (pre-0034 shape) ------------------------------
    op.create_table(
        "sale_item_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sale_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sale_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_stock_balances.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity_base", sa.Numeric(18, 4), nullable=False),
        sa.Column("cost_per_base", sa.Numeric(18, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sale_item_batches_sale_item_id", "sale_item_batches", ["sale_item_id"])
    op.create_index("ix_sale_item_batches_batch_id", "sale_item_batches", ["batch_id"])

    # ---- telegram_expiry_alert_state (pre-0034 shape) --------------------
    op.create_table(
        "telegram_expiry_alert_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("batch_no", sa.String(100), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("alert_level", sa.SmallInteger(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_telegram_expiry_alert_state_lot
        ON telegram_expiry_alert_state (
            product_id,
            COALESCE(batch_no, ''),
            expiry_date,
            alert_level
        )
        """
    )
    op.create_index(
        "ix_telegram_expiry_alert_state_product_id",
        "telegram_expiry_alert_state",
        ["product_id"],
    )
