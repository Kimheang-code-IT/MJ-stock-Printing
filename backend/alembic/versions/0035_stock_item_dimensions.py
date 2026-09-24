"""stock_transaction_items height / width / area_m2 (sold-by-area purchases).

Revision ID: 0035_stock_item_dimensions
Revises: 0034_remove_batch_expiry
Create Date: 2026-09-24

A purchase (Stock In) line may be received by area: the user enters a Height
and Width (metres) and the received quantity becomes the area in square metres
(height x width), mirroring the POS sold-by-area sale line. The dimensions are
stored on the stock-in line so the purchase report / edit form can reload them.

All three columns are nullable; count-based lines leave them NULL.
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_stock_item_dimensions"
down_revision = "0034_remove_batch_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_transaction_items", sa.Column("height", sa.Numeric(18, 4), nullable=True))
    op.add_column("stock_transaction_items", sa.Column("width", sa.Numeric(18, 4), nullable=True))
    op.add_column("stock_transaction_items", sa.Column("area_m2", sa.Numeric(18, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_transaction_items", "area_m2")
    op.drop_column("stock_transaction_items", "width")
    op.drop_column("stock_transaction_items", "height")
