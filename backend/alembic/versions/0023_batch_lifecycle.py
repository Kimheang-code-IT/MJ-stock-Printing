"""Batch management hardening: track_batch flag, batch lifecycle, ledger links.

Revision ID: 0023_batch_lifecycle
Revises: 0022_batch_fefo
Create Date: 2026-09-11

- products.track_batch: when true, Stock In lines MUST carry a batch_no and
  (when expiry_tracking) an expiry_date; unbatched synthetic lots stay the
  legacy path.
- batch_stock_balances: received_quantity ledger column, lifecycle status
  (ACTIVE | DEPLETED | EXPIRED), and a 6-decimal cost_per_base (quantities
  stay 4-decimal). Backfills: received = remaining, status derived from
  remaining/expiry (NULL expiry batches are never auto-marked EXPIRED).
- stock_movements.batch_id: optional FK to the consumed/received lot plus
  indexes for the FEFO lookup and movement click-through.
- sale_item_batches.cost_per_base widens to Numeric(18, 6) to match the
  batch cost precision.
- Indexes: batch_stock_balances(product_id, expiry_date), (expiry_date),
  (product_id, batch_no) as the identity index; stock_movements(batch_id).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_batch_lifecycle"
down_revision = "0022_batch_fefo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- products.track_batch -------------------------------------------
    op.add_column(
        "products",
        sa.Column(
            "track_batch",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ---- batch_stock_balances lifecycle + precision ----------------------
    op.add_column(
        "batch_stock_balances",
        sa.Column(
            "received_quantity",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "batch_stock_balances",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.alter_column(
        "batch_stock_balances",
        "unit_cost",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Numeric(18, 6),
        existing_nullable=False,
    )
    # Backfill the received ledger and lifecycle status from current state.
    op.execute(
        """
        UPDATE batch_stock_balances
        SET received_quantity = GREATEST(remaining_quantity, received_quantity)
        """
    )
    op.execute(
        """
        UPDATE batch_stock_balances
        SET status = CASE
            WHEN remaining_quantity <= 0 THEN 'DEPLETED'
            WHEN expiry_date IS NOT NULL AND expiry_date < CURRENT_DATE THEN 'EXPIRED'
            ELSE 'ACTIVE'
        END
        """
    )

    # ---- FEFO lookup + identity indexes ----------------------------------
    op.create_index(
        "ix_batch_stock_balances_product_expiry",
        "batch_stock_balances",
        ["product_id", "expiry_date"],
    )
    op.create_index(
        "ix_batch_stock_balances_expiry_date",
        "batch_stock_balances",
        ["expiry_date"],
    )

    # ---- stock_movements.batch_id ----------------------------------------
    op.add_column(
        "stock_movements",
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_stock_movements_batch_id",
        "stock_movements",
        "batch_stock_balances",
        ["batch_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_stock_movements_batch_id",
        "stock_movements",
        ["batch_id"],
    )

    # ---- sale_item_batches cost precision --------------------------------
    op.alter_column(
        "sale_item_batches",
        "cost_per_base",
        existing_type=sa.Numeric(18, 2),
        type_=sa.Numeric(18, 6),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "sale_item_batches",
        "cost_per_base",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Numeric(18, 2),
        existing_nullable=False,
    )
    op.drop_index("ix_stock_movements_batch_id", table_name="stock_movements")
    op.drop_constraint("fk_stock_movements_batch_id", "stock_movements", type_="foreignkey")
    op.drop_column("stock_movements", "batch_id")
    op.drop_index("ix_batch_stock_balances_expiry_date", table_name="batch_stock_balances")
    op.drop_index(
        "ix_batch_stock_balances_product_expiry", table_name="batch_stock_balances"
    )
    op.alter_column(
        "batch_stock_balances",
        "unit_cost",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Numeric(18, 2),
        existing_nullable=False,
    )
    op.drop_column("batch_stock_balances", "status")
    op.drop_column("batch_stock_balances", "received_quantity")
    op.drop_column("products", "track_batch")