"""remove units of measure (single-unit rewrite).

Revision ID: 0031_remove_uom
Revises: 0030_user_telegram_name
Create Date: 2026-09-19

The system no longer models Units of Measure (UOM): products, stock and
sales carry a single quantity unit. This migration removes the UOM master
data and every UOM / conversion snapshot, and normalizes historical sale
line quantities from the entered UOM to the base unit so cost/quantity
reporting stays consistent.

Upgrade:
- normalize sale_items (quantity, returned_quantity, unit_price) and
  sale_return_items.quantity to the base unit (factor_to_base is folded in).
- drop product_sale_price_uoms, products.uom_conversions, products.uom_id.
- drop units_of_measure.
- drop UOM snapshot columns from sale_items, stock_transaction_items,
  stock_movements and delivery_note_items.

Downgrade recreates the schema (UOM master data + snapshots) with neutral
defaults; historical converted quantities are not recovered.
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_remove_uom"
down_revision = "0030_user_telegram_name"
branch_labels = None
depends_on = None

# Spec section 2.1.3 seed examples (recreated on downgrade).
DEFAULT_UOMS = (
    ("PCS", "Piece", "pcs"),
    ("BOX", "Box", "box"),
    ("CAN", "Can", "can"),
    ("BTL", "Bottle", "btl"),
    ("KG", "Kilogram", "kg"),
    ("PACK", "Pack", "pack"),
)


def upgrade() -> None:
    # 1) Fold every converted sale line into the base unit so quantities and
    #    unit prices stay coherent after the factor column disappears.
    op.execute(
        """
        UPDATE sale_return_items sri
        SET quantity = sri.quantity * si.factor_to_base
        FROM sale_items si
        WHERE sri.sale_item_id = si.id
          AND si.factor_to_base IS NOT NULL
          AND si.factor_to_base > 0
          AND si.factor_to_base <> 1
        """
    )
    op.execute(
        """
        UPDATE sale_items
        SET quantity = quantity * factor_to_base,
            returned_quantity = returned_quantity * factor_to_base,
            unit_price = unit_price / factor_to_base
        WHERE factor_to_base IS NOT NULL
          AND factor_to_base > 0
          AND factor_to_base <> 1
        """
    )

    # 2) Per-UOM price rows and product pricing rows.
    op.drop_table("product_sale_price_uoms")
    op.drop_column("products", "uom_conversions")

    # 3) products.uom_id (FK + index) and the UOM master table.
    op.drop_index("ix_products_uom_id", table_name="products")
    op.drop_constraint("fk_products_uom_id", "products", type_="foreignkey")
    op.drop_column("products", "uom_id")
    op.drop_table("units_of_measure")

    # 4) UOM / conversion snapshots on historical documents.
    op.drop_column("sale_items", "uom_id")
    op.drop_column("sale_items", "uom_code")
    op.drop_column("sale_items", "uom_symbol")
    op.drop_column("sale_items", "factor_to_base")

    op.drop_column("stock_transaction_items", "uom_symbol")
    op.drop_column("stock_transaction_items", "entered_uom_id")
    op.drop_column("stock_transaction_items", "entered_uom_symbol")
    op.drop_column("stock_transaction_items", "entered_factor_to_base")
    op.drop_column("stock_transaction_items", "entered_quantity")

    op.drop_column("stock_movements", "uom_symbol")
    op.drop_column("delivery_note_items", "uom_symbol")


def downgrade() -> None:
    # 1) Recreate the UOM master table and its default rows.
    op.create_table(
        "units_of_measure",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_units_of_measure_code"),
    )
    op.bulk_insert(
        sa.table(
            "units_of_measure",
            sa.column("id", postgresql.UUID(as_uuid=True)),
            sa.column("code", sa.String),
            sa.column("name", sa.String),
            sa.column("symbol", sa.String),
            sa.column("status", sa.String),
        ),
        [
            {"id": uuid.uuid4(), "code": code, "name": name, "symbol": symbol, "status": "ACTIVE"}
            for code, name, symbol in DEFAULT_UOMS
        ],
    )

    # 2) products.uom_id (backfilled to PCS) + pricing rows.
    op.add_column("products", sa.Column("uom_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(
        """
        UPDATE products
        SET uom_id = u.id
        FROM units_of_measure u
        WHERE u.code = 'PCS' AND products.uom_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE products
        SET uom_id = (SELECT u.id FROM units_of_measure u ORDER BY u.code LIMIT 1)
        WHERE products.uom_id IS NULL
        """
    )
    op.alter_column("products", "uom_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.create_foreign_key(
        "fk_products_uom_id", "products", "units_of_measure", ["uom_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_products_uom_id", "products", ["uom_id"])
    op.add_column("products", sa.Column("uom_conversions", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # 3) Per-UOM price rows: one base-UOM row per version.
    op.create_table(
        "product_sale_price_uoms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "price_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_sale_prices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uom_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("units_of_measure.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("uom_symbol", sa.String(length=50), nullable=True),
        sa.Column("factor_to_base", sa.Numeric(18, 6), nullable=False),
        sa.Column("sale_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("is_default_sale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("price_version_id", "uom_id", name="uq_sale_price_uoms_version_uom"),
    )
    op.create_index("ix_product_sale_price_uoms_version", "product_sale_price_uoms", ["price_version_id"])
    op.execute(
        """
        INSERT INTO product_sale_price_uoms
        (id, price_version_id, uom_id, factor_to_base, sale_price, is_default_sale)
        SELECT gen_random_uuid(), v.id, p.uom_id, 1, v.sale_price, TRUE
        FROM product_sale_prices v
        JOIN products p ON p.id = v.product_id
        WHERE NOT EXISTS (
            SELECT 1 FROM product_sale_price_uoms c
            WHERE c.price_version_id = v.id AND c.uom_id = p.uom_id
        )
        """
    )

    # 4) Document snapshots.
    op.add_column("sale_items", sa.Column("uom_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "sale_items",
        sa.Column("factor_to_base", sa.Numeric(18, 6), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("sale_items", sa.Column("uom_code", sa.String(50), nullable=True))
    op.add_column("sale_items", sa.Column("uom_symbol", sa.String(20), nullable=True))

    op.add_column("stock_transaction_items", sa.Column("uom_symbol", sa.String(20), nullable=True))
    op.add_column("stock_transaction_items", sa.Column("entered_uom_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("stock_transaction_items", sa.Column("entered_uom_symbol", sa.String(20), nullable=True))
    op.add_column("stock_transaction_items", sa.Column("entered_factor_to_base", sa.Numeric(18, 6), nullable=True))
    op.add_column("stock_transaction_items", sa.Column("entered_quantity", sa.Numeric(18, 4), nullable=True))

    op.add_column("stock_movements", sa.Column("uom_symbol", sa.String(20), nullable=True))
    op.add_column("delivery_note_items", sa.Column("uom_symbol", sa.String(20), nullable=True))
