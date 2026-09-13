"""Product FIFO costing option.

Revision ID: 0018_product_fifo
Revises: 0017_drop_invoice_pdf_object_key
Create Date: 2026-10-08

Adds `products.fifo` (boolean, default false). When enabled for a product,
outbound stock movements (POS sale, damage, expiry, adjustment out) are
costed from the oldest remaining stock-in lots (first in, first out) instead
of the weighted average cost.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_product_fifo"
down_revision = "0017_drop_invoice_pdf_object_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("fifo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("products", "fifo")
