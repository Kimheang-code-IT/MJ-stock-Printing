from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BackupRunRequest(BaseModel):
    # Reserved for future selective backups; an empty list means "all tables".
    tables: list[str] | None = None


class BackupRestoreRequest(BaseModel):
    tables: list[str] | None = None
    dry_run: bool = Field(default=False, alias="dryRun")
    confirm: bool = False

    model_config = ConfigDict(populate_by_name=True)


class BackupJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trigger: str
    status: str
    spreadsheet_id: str | None
    tables_total: int
    tables_succeeded: int
    tables_failed: int
    rows_backed_up: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class BackupTableStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    table_name: str
    last_version: int
    last_backup_at: datetime | None
    last_record_count: int
    last_error: str | None


class BackupRestoreResultOut(BaseModel):
    dry_run: bool
    tables: int
    records: int
    inserted: int
    updated: int
    skipped: int
    details: list[dict]
