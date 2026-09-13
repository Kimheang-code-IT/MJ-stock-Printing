"""Batch stock ledger + FEFO sale allocation + outbound-line UOM entries.

Revision ID: 0022_batch_fefo
Revises: 0021_barcode_first_product
Create Date: 2026-09-11

- batch_stock_balances: per (product, batch_no) remaining base quantity,
  expiry, and cost, written only by the canonical mutation service under row
  lock. The product's stock_balances row remains the materialized total.
  Expiry is a recorded attribute of the lot (stamped from the purchase), not
  part of the batch identity.
- sale_item_batches: per sold line, base-quantity batch allocations with a
  cost-per-base snapshot. SUM(quantity_base) == quantity x factor_to_base.
- stock_transaction_items entered_uom_id / entered_uom_symbol /
  entered_factor_to_base / entered_quantity: preserve the UOM the user typed
  on Damage / Expiry / Purchase Return lines; ledger + balances stay base-UOM.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_batch_fefo"
down_revision = "0021_barcode_first_product"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- batch_stock_balances -------------------------------------------
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
        sa.Column("remaining_quantity", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
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
    )
    op.create_index("ix_batch_stock_balances_product_id", "batch_stock_balances", ["product_id"])

    # ---- sale_item_batches ----------------------------------------------
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
        sa.Column("cost_per_base", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Index("ix_sale_item_batches_sale_item_id", "sale_item_id"),
        sa.Index("ix_sale_item_batches_batch_id", "batch_id"),
    )

    # ---- outbound operation entered UOM ---------------------------------
    op.add_column(
        "stock_transaction_items",
        sa.Column("entered_uom_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "stock_transaction_items",
        sa.Column("entered_uom_symbol", sa.String(20), nullable=True),
    )
    op.add_column(
        "stock_transaction_items",
        sa.Column("entered_factor_to_base", sa.Numeric(18, 6), nullable=True),
    )
    op.add_column(
        "stock_transaction_items",
        sa.Column("entered_quantity", sa.Numeric(18, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stock_transaction_items", "entered_quantity")
    op.drop_column("stock_transaction_items", "entered_factor_to_base")
    op.drop_column("stock_transaction_items", "entered_uom_symbol")
    op.drop_column("stock_transaction_items", "entered_uom_id")
    op.drop_table("sale_item_batches")
    op.drop_table("batch_stock_balances")