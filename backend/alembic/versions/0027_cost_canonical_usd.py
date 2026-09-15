"""canonical USD cost ledger (F2: cross-currency COGS / valuation)

Cost ledgers (`stock_movements.unit_cost`, `stock_balances.average_cost`,
`batch_stock_balances.unit_cost`, `sale_items.unit_cost`,
`sale_item_batches.cost_per_base`) move to a single canonical currency (USD).
Documents keep their own currency: `stock_transactions` / `sales` amounts and
`stock_transaction_items.unit_cost` stay in the document currency.

Historical rows are converted in place using each row's linked document
currency + exchange rate, so same-currency history is unchanged and the
weighted-average balance is replayed from the converted inbound movements.
No schema change — data normalization only.

Revision ID: 0027_cost_canonical_usd
Revises: 0026_drop_party_email
Create Date: 2026-09-14
"""

from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from alembic import op

revision = "0027_cost_canonical_usd"
down_revision = "0026_drop_party_email"
branch_labels = None
depends_on = None

TWO = Decimal("0.01")


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Inbound/outbound movements linked to a purchase → USD.
    bind.execute(sa.text(
        """
        UPDATE stock_movements AS m
        SET unit_cost = ROUND(m.unit_cost / t.exchange_rate, 2)
        FROM stock_transactions AS t
        WHERE m.reference_type = 'stock_transaction'
          AND m.reference_id = t.id
          AND t.currency = 'KHR'
          AND t.exchange_rate > 0
        """
    ))
    # 2) Sale-linked movements (SALE / SALE_RETURN) → USD.
    bind.execute(sa.text(
        """
        UPDATE stock_movements AS m
        SET unit_cost = ROUND(m.unit_cost / s.exchange_rate, 2)
        FROM sales AS s
        WHERE m.reference_type = 'sale'
          AND m.reference_id = s.id
          AND s.currency = 'KHR'
          AND s.exchange_rate > 0
        """
    ))

    # 3) Replay the weighted-average ledger in USD to recompute each balance.
    rows = bind.execute(sa.text(
        """
        SELECT product_id, movement_type, quantity_delta, unit_cost
        FROM stock_movements
        ORDER BY product_id, created_at, id
        """
    )).fetchall()
    state: dict[str, tuple[Decimal, Decimal]] = {}
    for product_id, movement_type, delta_raw, cost_raw in rows:
        key = str(product_id)
        qty, avg = state.get(key, (Decimal("0"), Decimal("0")))
        delta = Decimal(delta_raw)
        if movement_type == "STOCK_IN" and delta > 0 and qty >= 0:
            total = qty + delta
            if total > 0:
                avg = ((qty * avg + delta * Decimal(cost_raw)) / total).quantize(TWO, rounding=ROUND_HALF_UP)
            else:
                avg = Decimal(cost_raw).quantize(TWO, rounding=ROUND_HALF_UP)
        state[key] = (qty + delta, avg)
    for pid, (_qty, avg) in state.items():
        bind.execute(
            sa.text("UPDATE stock_balances SET average_cost = :cost WHERE product_id = :pid"),
            {"cost": avg, "pid": pid},
        )

    # 4) Batch lot cost = latest converted inbound movement of that lot.
    bind.execute(sa.text(
        """
        UPDATE batch_stock_balances AS b
        SET unit_cost = sub.unit_cost
        FROM (
            SELECT DISTINCT ON (m.product_id, m.batch_no)
                   m.product_id, m.batch_no, m.unit_cost
            FROM stock_movements AS m
            WHERE m.movement_type = 'STOCK_IN' AND m.quantity_delta > 0
            ORDER BY m.product_id, m.batch_no, m.created_at DESC, m.id DESC
        ) AS sub
        WHERE b.product_id = sub.product_id AND b.batch_no = sub.batch_no
        """
    ))

    # 5) Sale-item cost snapshots → USD (document = sale currency).
    bind.execute(sa.text(
        """
        UPDATE sale_items AS si
        SET unit_cost = ROUND(si.unit_cost / s.exchange_rate, 2)
        FROM sales AS s
        WHERE si.sale_id = s.id
          AND s.currency = 'KHR'
          AND s.exchange_rate > 0
        """
    ))
    bind.execute(sa.text(
        """
        UPDATE sale_item_batches AS sib
        SET cost_per_base = ROUND(sib.cost_per_base / s.exchange_rate, 6)
        FROM sale_items AS si
        JOIN sales AS s ON s.id = si.sale_id
        WHERE sib.sale_item_id = si.id
          AND s.currency = 'KHR'
          AND s.exchange_rate > 0
        """
    ))


def downgrade() -> None:
    """Best-effort reversal: multiply USD costs back by the linked rate."""
    bind = op.get_bind()
    bind.execute(sa.text(
        """
        UPDATE stock_movements AS m
        SET unit_cost = ROUND(m.unit_cost * t.exchange_rate, 2)
        FROM stock_transactions AS t
        WHERE m.reference_type = 'stock_transaction'
          AND m.reference_id = t.id
          AND t.currency = 'KHR'
          AND t.exchange_rate > 0
        """
    ))
    bind.execute(sa.text(
        """
        UPDATE stock_movements AS m
        SET unit_cost = ROUND(m.unit_cost * s.exchange_rate, 2)
        FROM sales AS s
        WHERE m.reference_type = 'sale'
          AND m.reference_id = s.id
          AND s.currency = 'KHR'
          AND s.exchange_rate > 0
        """
    ))
    bind.execute(sa.text(
        """
        UPDATE sale_items AS si
        SET unit_cost = ROUND(si.unit_cost * s.exchange_rate, 2)
        FROM sales AS s
        WHERE si.sale_id = s.id
          AND s.currency = 'KHR'
          AND s.exchange_rate > 0
        """
    ))
    bind.execute(sa.text(
        """
        UPDATE sale_item_batches AS sib
        SET cost_per_base = ROUND(sib.cost_per_base * s.exchange_rate, 6)
        FROM sale_items AS si
        JOIN sales AS s ON s.id = si.sale_id
        WHERE sib.sale_item_id = si.id
          AND s.currency = 'KHR'
          AND s.exchange_rate > 0
        """
    ))
