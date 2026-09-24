"""Remove discount from sales and purchases.

Revision ID: 0033_remove_discount
Revises: 0032_sale_item_dimensions
Create Date: 2026-09-21

The discount feature is removed system-wide:
- sales.discount_amount (sale-header discount total)
- sale_items.discount_amount / sale_items.discount_percent (line discounts)
- stock_transactions.discount_amount (purchase-header discount)
"""

import sqlalchemy as sa
from alembic import op

revision = "0033_remove_discount"
down_revision = "0032_sale_item_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("sale_items", "discount_percent")
    op.drop_column("sale_items", "discount_amount")
    op.drop_column("sales", "discount_amount")
    op.drop_column("stock_transactions", "discount_amount")


def downgrade() -> None:
    op.add_column(
        "stock_transactions",
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
    )
    op.add_column(
        "sales",
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
    )
    op.add_column(
        "sale_items",
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0.00"),
    )
    op.add_column(
        "sale_items",
        sa.Column("discount_percent", sa.Numeric(5, 2), nullable=False, server_default="0"),
    )
