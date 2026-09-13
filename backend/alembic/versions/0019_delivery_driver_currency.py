"""Delivery note driver name and currency.

Revision ID: 0019_delivery_driver_currency
Revises: 0018_product_fifo
Create Date: 2026-09-10

Adds `delivery_notes.driver_name` (optional delivery driver) and
`delivery_notes.currency` (USD|KHR, defaults USD). The currency gates which
deliverable invoices can be added to the note — all invoices on one note must
share the note's currency (their currencies are never mixed on one note).
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_delivery_driver_currency"
down_revision = "0018_product_fifo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_notes",
        sa.Column("driver_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "delivery_notes",
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
    )
    op.add_column(
        "delivery_note_items",
        sa.Column("note", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("delivery_note_items", "note")
    op.drop_column("delivery_notes", "currency")
    op.drop_column("delivery_notes", "driver_name")