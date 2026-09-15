"""product default supplier (fast purchasing)

Adds `products.supplier_id` — an optional default supplier that prefills the
purchase (Stock In) form's supplier. The supplier is still changeable per
purchase; this column only supplies the fingerprint default.

Revision ID: 0028_product_supplier
Revises: 0027_cost_canonical_usd
Create Date: 2026-09-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_product_supplier"
down_revision = "0027_cost_canonical_usd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_products_supplier_id",
        "products",
        "suppliers",
        ["supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_products_supplier_id", "products", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("ix_products_supplier_id", table_name="products")
    op.drop_constraint("fk_products_supplier_id", "products", type_="foreignkey")
    op.drop_column("products", "supplier_id")
