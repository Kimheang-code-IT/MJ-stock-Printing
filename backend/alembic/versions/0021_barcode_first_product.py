"""Barcode as the operational product identifier.

Revision ID: 0021_barcode_first_product
Revises: 0020_delivery_fulfillment_fields
Create Date: 2026-09-10

- `products.sku` becomes optional (NULL allowed, UNIQUE retained so any
  legacy code value stays unique); UUID PKs remain the internal identity.
- `products.barcode` becomes NOT NULL and is backfilled from `sku` for every
  product without one, then each unique barcode is re-issued from the
  sequence prefix `BAR-<n>` when the backfill value is already taken.
- `sale_items.sku` becomes nullable (sale lines snapshot `barcode` already).
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_barcode_first_product"
down_revision = "0020_delivery_fulfillment_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. SKU becomes optional; keep the UNIQUE constraint for legacy values.
    op.alter_column("products", "sku", existing_type=sa.String(100), nullable=True)

    # 2. Backfill barcodes: copy sku when available and NOT already taken by
    #    another product's barcode (sku and barcode were independent
    #    namespaces before this migration, so a sku can collide with an
    #    existing barcode); otherwise derive one from the row's UUID PK
    #    (gen_random_uuid() may not be installed — the id column is always
    #    populated). The PK-derived fallback is itself collision-guarded.
    op.execute(
        """
        UPDATE products
        SET barcode = sku
        WHERE barcode IS NULL
          AND sku IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM products other
              WHERE other.barcode = products.sku
          )
        """
    )
    op.execute(
        """
        UPDATE products
        SET barcode = 'BAR-' || left(replace(products.id::text, '-', ''), 12)
        WHERE barcode IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM products other
              WHERE other.id <> products.id
                AND other.barcode = 'BAR-' || left(replace(products.id::text, '-', ''), 12)
          )
        """
    )
    # Last-resort random derivation (md5 of id + clock) for anything a
    # pre-existing barcode could still collide with; effectively never runs.
    op.execute(
        """
        UPDATE products
        SET barcode = 'BAR-' || left(md5(products.id::text || clock_timestamp()::text), 12)
        WHERE barcode IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM products other
              WHERE other.id <> products.id
                AND other.barcode = 'BAR-' || left(md5(products.id::text || clock_timestamp()::text), 12)
          )
        """
    )

    # 3. Barcode is now the required operational identifier.
    op.alter_column("products", "barcode", existing_type=sa.String(100), nullable=False)

    # 4. Sale line snapshots keep the barcode; sku snapshot becomes optional.
    op.alter_column("sale_items", "sku", existing_type=sa.String(100), nullable=True)


def downgrade() -> None:
    op.alter_column("sale_items", "sku", existing_type=sa.String(100), nullable=False)
    op.alter_column("products", "barcode", existing_type=sa.String(100), nullable=True)
    op.execute("UPDATE products SET sku = barcode WHERE sku IS NULL")
    op.alter_column("products", "sku", existing_type=sa.String(100), nullable=False)