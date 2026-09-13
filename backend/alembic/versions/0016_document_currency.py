"""Document currency + exchange rate (purchase, sale, expense, debts).

Revision ID: 0016_document_currency
Revises: 0015_stock_in_tax_discount
Create Date: 2026-10-06

- Every money document carries the currency it was recorded in (USD | KHR)
  and the exchange rate applied (KHR per 1 USD, 1 for USD documents).
  All amounts on a document are in its own currency — never mixed.
- Debts inherit the currency of their source document so payments stay in
  the same currency as the debt.
- The Finance report normalizes KHR rows to USD via exchange_rate.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_document_currency"
down_revision = "0015_stock_in_tax_discount"
branch_labels = None
depends_on = None

TABLES = ("stock_transactions", "sales", "expenses", "supplier_debts", "customer_debts")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        )
        op.add_column(
            table,
            sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "exchange_rate")
        op.drop_column(table, "currency")
