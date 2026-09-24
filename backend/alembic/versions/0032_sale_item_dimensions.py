"""sale_items height / width / area_m2 (sold-by-area lines).

Revision ID: 0032_sale_item_dimensions
Revises: 0031_remove_uom
Create Date: 2026-09-19

POS lines may be sold by area: the cashier enters a Height and Width (metres)
and the billed quantity becomes the area in square metres (height × width).
The dimensions are stored on the sale line for the printed invoice / reprints.

All three columns are nullable; count-based lines leave them NULL.
"""

import sqlalchemy as sa
from alembic import op

revision = "0032_sale_item_dimensions"
down_revision = "0031_remove_uom"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sale_items", sa.Column("height", sa.Numeric(18, 4), nullable=True))
    op.add_column("sale_items", sa.Column("width", sa.Numeric(18, 4), nullable=True))
    op.add_column("sale_items", sa.Column("area_m2", sa.Numeric(18, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("sale_items", "area_m2")
    op.drop_column("sale_items", "width")
    op.drop_column("sale_items", "height")
