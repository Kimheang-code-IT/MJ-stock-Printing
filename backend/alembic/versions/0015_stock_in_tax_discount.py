"""Stock In (purchase) header discount + tax.

Revision ID: 0015_stock_in_tax_discount
Revises: 0014_purchase_returns
Create Date: 2026-10-05

- stock_transactions.discount_amount / tax_amount: document-level purchase
  adjustments for POST /stock/in (Stock In = purchase). total_amount becomes
  subtotal − discount + tax; the supplier debt is created from that total.
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_stock_in_tax_discount"
down_revision = "0014_purchase_returns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_transactions",
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
    )
    op.add_column(
        "stock_transactions",
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
    )


def downgrade() -> None:
    op.drop_column("stock_transactions", "tax_amount")
    op.drop_column("stock_transactions", "discount_amount")
