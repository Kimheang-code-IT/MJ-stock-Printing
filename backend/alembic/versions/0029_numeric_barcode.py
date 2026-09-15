"""numeric product barcodes

Auto-issued product barcodes switch from `BAR-<hex>` to a digits-only
13-character code so the printed sticker shows a plain number (and scans at
POS). This migration re-issues any existing auto-generated `BAR-%` barcode as
a deterministic unique numeric code; barcodes entered by hand are untouched.

Revision ID: 0029_numeric_barcode
Revises: 0028_product_supplier
Create Date: 2026-09-15
"""

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0029_numeric_barcode"
down_revision = "0028_product_supplier"
branch_labels = None
depends_on = None

_MODULO = 10**13


def _derive(row_id: object) -> str:
    """Deterministic 13-digit code from a product id (md5, zero-padded)."""
    digest = hashlib.md5(str(row_id).encode("utf-8")).hexdigest()
    value = int(digest[:15], 16) % _MODULO
    return f"{value:013d}"


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, barcode FROM products WHERE barcode LIKE 'BAR-%'")
    ).fetchall()
    if not rows:
        return

    taken = {
        row[0]
        for row in bind.execute(sa.text("SELECT barcode FROM products")).fetchall()
    }

    for product_id, _old in rows:
        candidate = _derive(product_id)
        while candidate in taken:
            candidate = f"{(int(candidate) + 1) % _MODULO:013d}"
        taken.add(candidate)
        bind.execute(
            sa.text("UPDATE products SET barcode = :barcode WHERE id = :id"),
            {"barcode": candidate, "id": product_id},
        )


def downgrade() -> None:
    # Original random `BAR-<hex>` identifiers are not recoverable; leave the
    # numeric codes in place.
    pass
