"""Batch ledger integrity constraints.

Revision ID: 0024_batch_integrity
Revises: 0023_batch_lifecycle
Create Date: 2026-09-11

Enforces at the database level what the canonical stock-mutation service
already maintains in transactions (spec: batch quantities are never negative
and never exceed the received quantity of the lot):

- batch_stock_balances.remaining_quantity >= 0
- batch_stock_balances.received_quantity >= remaining_quantity

Backfill: 0023 set received_quantity = GREATEST(remaining, received), so every
existing row already satisfies both constraints; no data repair is needed.
All writes go through the canonical mutation service; there is no endpoint
that edits batch quantities directly.
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_batch_integrity"
down_revision = "0023_batch_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_batch_remaining_nonneg",
        "batch_stock_balances",
        sa.text("remaining_quantity >= 0"),
    )
    op.create_check_constraint(
        "ck_batch_received_gte_remaining",
        "batch_stock_balances",
        sa.text("received_quantity >= remaining_quantity"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_batch_received_gte_remaining", "batch_stock_balances", type_="check")
    op.drop_constraint("ck_batch_remaining_nonneg", "batch_stock_balances", type_="check")
