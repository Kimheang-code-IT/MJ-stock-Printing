"""Drop the unused customers.email / suppliers.email columns.

Revision ID: 0026_drop_party_email
Revises: 0025_sale_price_version_uoms
Create Date: 2026-09-14

The party ``email`` columns were never part of the API contract: they are
absent from the Customer/Supplier create/update/out schemas, the services
always wrote ``None`` on create and popped ``email`` on update, nothing read
them, and the SPA strips the field before sending. Verified 0 non-null values
in the deployed database. Contacts are captured through phone/address only.
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_drop_party_email"
down_revision = "0025_sale_price_version_uoms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("customers", "email")
    op.drop_column("suppliers", "email")


def downgrade() -> None:
    op.add_column("customers", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("suppliers", sa.Column("email", sa.String(length=255), nullable=True))
