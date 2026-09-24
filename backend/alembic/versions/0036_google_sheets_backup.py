"""Google Sheets backup ledger (jobs, per-table state, record versions).

Revision ID: 0036_google_sheets_backup
Revises: 0035_stock_item_dimensions
Create Date: 2026-09-24

Adds three bookkeeping tables used by the automatic Google Sheets backup
feature. They are intentionally outside the business schema so a Sheets outage
never touches application transactions:

- backup_jobs         — one row per backup/restore attempt.
- backup_table_states — per-table sync cursor (last version / row count / error).
- backup_records      — append-only ledger of backed-up record versions; the
  unique (table_name, record_id, version) constraint prevents duplicates.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_google_sheets_backup"
down_revision = "0035_stock_item_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("spreadsheet_id", sa.String(length=200), nullable=True),
        sa.Column("tables_total", sa.Integer(), nullable=False),
        sa.Column("tables_succeeded", sa.Integer(), nullable=False),
        sa.Column("tables_failed", sa.Integer(), nullable=False),
        sa.Column("rows_backed_up", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "backup_table_states",
        sa.Column("table_name", sa.String(length=200), primary_key=True),
        sa.Column("last_version", sa.Integer(), nullable=False),
        sa.Column("last_backup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_record_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
    )

    op.create_table(
        "backup_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("table_name", sa.String(length=200), nullable=False),
        sa.Column("record_id", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("backup_version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "backed_up_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("table_name", "record_id", "version"),
    )
    op.create_index(
        "ix_backup_records_table_record", "backup_records", ["table_name", "record_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_backup_records_table_record", table_name="backup_records")
    op.drop_table("backup_records")
    op.drop_table("backup_table_states")
    op.drop_table("backup_jobs")
