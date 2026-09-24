"""Google Sheets backup ledger.

Three tables keep the backup feature independent from the business schema:

- `backup_jobs`        — one row per backup/restore attempt (success or failure).
- `backup_table_states` — per-table sync cursor (last version / record count).
- `backup_records`     — append-only ledger of every record version that was
  pushed to Google Sheets. The `(table_name, record_id, version)` unique
  constraint is what prevents a record from being backed up twice.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BackupJob(Base):
    __tablename__ = "backup_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    spreadsheet_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tables_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tables_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tables_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_backed_up: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackupTableState(Base):
    __tablename__ = "backup_table_states"

    table_name: Mapped[str] = mapped_column(String(200), primary_key=True)
    last_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BackupRecord(Base):
    __tablename__ = "backup_records"
    __table_args__ = (
        UniqueConstraint("table_name", "record_id", "version"),
        Index("ix_backup_records_table_record", "table_name", "record_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    record_id: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    backup_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    backed_up_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
