"""Delivery note fulfillment fields and extended status model.

Revision ID: 0020_delivery_fulfillment_fields
Revises: 0019_delivery_driver_currency
Create Date: 2026-09-10

Adds the fulfillment header fields (delivery_date, vehicle_no, delivery_fee,
received_by). Status values stay stored in `delivery_notes.status`
(varchar) — the extended vocabulary (PARTIALLY_DELIVERED, FAILED, RETURNED)
needs no DDL, only service-level transition rules.
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_delivery_fulfillment_fields"
down_revision = "0019_delivery_driver_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_notes",
        sa.Column("delivery_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "delivery_notes",
        sa.Column("vehicle_no", sa.String(length=60), nullable=True),
    )
    op.add_column(
        "delivery_notes",
        sa.Column(
            "delivery_fee",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "delivery_notes",
        sa.Column("received_by", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("delivery_notes", "received_by")
    op.drop_column("delivery_notes", "delivery_fee")
    op.drop_column("delivery_notes", "vehicle_no")
    op.drop_column("delivery_notes", "delivery_date")