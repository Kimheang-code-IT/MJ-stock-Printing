"""Sale-price versions gain batch scope + per-UOM price rows.

Revision ID: 0025_sale_price_version_uoms
Revises: 0024_batch_integrity
Create Date: 2026-10-04

- product_sale_prices: + batch_no (optional; NULL = general pricing scope),
  purchase_date, expiry_date. The one-active invariant widens from
  "one active per product" to "one active per (product, batch scope)" via a
  functional partial unique index on COALESCE(batch_no, '').
- product_sale_price_uoms (NEW): the UOM price rows inside one version —
  (uom_id, factor_to_base, sale_price, is_default_sale). The version-level
  sale_price stays the base/default-sale UOM price and keeps mirroring
  products.selling_price.
- Data migration: every existing version gets a base-UOM child row; the
  currently ACTIVE versions additionally get child rows from the product's
  uom_conversions pricing rows so per-UOM POS prices keep working.
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_sale_price_version_uoms"
down_revision = "0024_batch_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_sale_prices",
        sa.Column("batch_no", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "product_sale_prices",
        sa.Column("purchase_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "product_sale_prices",
        sa.Column("expiry_date", sa.Date(), nullable=True),
    )

    # One ACTIVE version per product + batch scope ('' = general pricing).
    op.drop_index("uq_product_sale_prices_one_active", table_name="product_sale_prices")
    op.execute(
        "CREATE UNIQUE INDEX uq_product_sale_prices_one_active_scope "
        "ON product_sale_prices (product_id, (COALESCE(batch_no, ''))) "
        "WHERE is_active"
    )

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
    op.create_index(
        "ix_product_sale_price_uoms_version",
        "product_sale_price_uoms",
        ["price_version_id"],
    )

    # Seed child rows: base-UOM row for every version (factor 1, same price);
    # the ACTIVE version also carries the product's pricing-row UOM prices.
    conn = op.get_bind()
    versions = conn.execute(
        sa.text("SELECT id, product_id, sale_price, is_active FROM product_sale_prices")
    ).fetchall()
    for version_id, product_id, sale_price, is_active in versions:
        product = conn.execute(
            sa.text("SELECT uom_id, uom_conversions FROM products WHERE id = :pid"),
            {"pid": str(product_id)},
        ).fetchone()
        if product is None:
            continue
        base_uom = str(product[0])
        conn.execute(
            sa.text(
                "INSERT INTO product_sale_price_uoms "
                "(id, price_version_id, uom_id, factor_to_base, sale_price, is_default_sale) "
                "SELECT gen_random_uuid(), :vid, :uom, 1, :price, TRUE WHERE NOT EXISTS ("
                "  SELECT 1 FROM product_sale_price_uoms WHERE price_version_id = :vid AND uom_id = :uom)"
            ),
            {"vid": str(version_id), "uom": base_uom, "price": str(sale_price)},
        )
        if not is_active:
            continue
        try:
            conversions = json.loads(product[1] or "[]")
        except Exception:
            conversions = []
        for row in conversions if isinstance(conversions, list) else []:
            uom_id = str(row.get("uom_id") or "")
            if not uom_id or uom_id == base_uom:
                continue
            try:
                price = float(row.get("sale_price") or 0)
                factor = float(row.get("factor_to_base") or 1)
            except (TypeError, ValueError):
                continue
            if price <= 0 or factor <= 0:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO product_sale_price_uoms "
                    "(id, price_version_id, uom_id, uom_symbol, factor_to_base, sale_price, is_default_sale) "
                    "VALUES (gen_random_uuid(), :vid, :uom, :sym, :factor, :price, FALSE)"
                ),
                {
                    "vid": str(version_id),
                    "uom": uom_id,
                    "sym": str(row.get("uom_symbol") or "")[:50] or None,
                    "factor": str(factor),
                    "price": str(price),
                },
            )


def downgrade() -> None:
    op.drop_table("product_sale_price_uoms")
    op.drop_index("uq_product_sale_prices_one_active_scope", table_name="product_sale_prices")
    op.create_index(
        "uq_product_sale_prices_one_active",
        "product_sale_prices",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.drop_column("product_sale_prices", "expiry_date")
    op.drop_column("product_sale_prices", "purchase_date")
    op.drop_column("product_sale_prices", "batch_no")
