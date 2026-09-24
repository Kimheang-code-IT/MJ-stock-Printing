"""Remove the versioned sale-pricing table and all product barcodes.

Revision ID: 0033_remove_pricing_barcode
Revises: 0033_remove_discount
Create Date: 2026-09-21

The system no longer uses the versioned POS pricing feature
(`product_sale_prices`) or barcodes. Products keep a single
`cost_price` / `selling_price`; POS charges `selling_price`.

Upgrade (data loss, irreversible):
- drop `product_sale_prices` (and its indexes);
- drop `products.barcode`;
- drop `sale_items.barcode`.

Downgrade recreates the table/columns in their pre-0033 shape (barcodes are
backfilled from `sku`/UUID; the pricing table is recreated empty).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_remove_pricing_barcode"
down_revision = "0033_remove_discount"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("product_sale_prices")
    op.drop_column("sale_items", "barcode")
    op.drop_column("products", "barcode")


def downgrade() -> None:
    # 1. products.barcode: add nullable, backfill, then require NOT NULL.
    op.add_column("products", sa.Column("barcode", sa.String(length=100), nullable=True))
    op.execute(
        "UPDATE products SET barcode = sku "
        "WHERE barcode IS NULL AND sku IS NOT NULL"
    )
    op.execute(
        "UPDATE products SET barcode = 'BAR-' || left(replace(id::text, '-', ''), 12) "
        "WHERE barcode IS NULL"
    )
    op.create_unique_constraint("uq_products_barcode", "products", ["barcode"])
    op.alter_column("products", "barcode", existing_type=sa.String(100), nullable=False)

    # 2. sale_items.barcode snapshot.
    op.add_column("sale_items", sa.Column("barcode", sa.String(length=100), nullable=True))

    # 3. product_sale_prices (recreated empty, pre-0033 shape).
    op.create_table(
        "product_sale_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sale_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("batch_no", sa.String(length=120), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("product_id", "version", name="uq_product_sale_prices_product_version"),
    )
    op.create_index("ix_product_sale_prices_product_id", "product_sale_prices", ["product_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_product_sale_prices_one_active_scope "
        "ON product_sale_prices (product_id, (COALESCE(batch_no, ''))) "
        "WHERE is_active"
    )
