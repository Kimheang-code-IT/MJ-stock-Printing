"""Stop archiving invoice files (spec: POS invoices are browser/OS print of HTML only).

Revision ID: 0017_drop_invoice_pdf_object_key
Revises: 0016_document_currency
Create Date: 2026-10-06

- Drops `sales.invoice_pdf_object_key`. The system never stores invoice
  files; printing connects to the printer through the browser/OS print of
  the HTML receipt (`GET /pos/sales/{id}/receipt`).
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_drop_invoice_pdf_object_key"
down_revision = "0016_document_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("sales", "invoice_pdf_object_key")


def downgrade() -> None:
    op.add_column("sales", sa.Column("invoice_pdf_object_key", sa.String(500), nullable=True))
