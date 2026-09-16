"""add users.telegram_name

A human-readable label for a user's linked Telegram account, editable by an
administrator on Administration → Users alongside the Chat ID.

Revision ID: 0030_user_telegram_name
Revises: 0029_numeric_barcode
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_user_telegram_name"
down_revision = "0029_numeric_barcode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_name", sa.String(150), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "telegram_name")
