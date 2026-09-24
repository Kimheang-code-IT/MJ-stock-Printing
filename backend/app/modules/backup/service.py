"""Automatic Google Sheets backup and restore.

Design notes
------------
* Every database table discovered from the SQLAlchemy metadata gets its own
  spreadsheet tab. New tables and new columns are picked up automatically.
* Backups are **append-only**: a changed record is written as a new row with a
  higher ``record_version`` instead of overwriting history, so nothing is ever
  deleted and the full version history can be restored.
* A local ledger (`backup_records`) tracks the latest ``(version, content_hash)``
  per record. The unique ``(table_name, record_id, version)`` constraint stops a
  record from being backed up twice.
* Backup runs are isolated: each table runs in its own savepoint and the whole
  job runs in its own session, so a Google Sheets outage can never roll back or
  block a normal application transaction.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.backup.repository import BackupRepository
from app.modules.backup.sheets import (
    GSpreadSheetsClient,
    SheetsClient,
    SheetsError,
    parse_service_account_json,
)

logger = logging.getLogger("mj.backup")

META_COLUMNS = [
    "backup_at",
    "backup_version",
    "table_name",
    "record_id",
    "operation",
    "record_version",
]
# Internal/backup bookkeeping tables are never backed up into themselves.
SKIPPED_TABLES = frozenset(
    {"backup_jobs", "backup_records", "backup_table_states", "alembic_version"}
)
SECRET_MASK = "********"
VALID_INTERVALS = (1, 3, 6, 12, 24)


@dataclass
class BackupConfig:
    enabled: bool
    interval_hours: int
    spreadsheet_id: str
    service_account_json: str

    @property
    def configured(self) -> bool:
        return bool(self.spreadsheet_id and self.service_account_json)


# ------------------------------------------------------------------ helpers


def _now() -> datetime:
    return datetime.now(timezone.utc)


def serialize(value: Any) -> Any:
    """Turn a database value into a spreadsheet-safe string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return str(value)


def content_hash(values: dict[str, Any]) -> str:
    import hashlib

    payload = json.dumps(
        {key: serialize(value) for key, value in values.items()},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def coerce(column, raw: Any) -> Any:
    """Convert a spreadsheet cell back into the column's Python type."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    try:
        pytype = column.type.python_type
    except (NotImplementedError, AttributeError):
        return text
    if pytype is uuid.UUID:
        return uuid.UUID(text)
    if pytype is datetime:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    if pytype is date:
        return date.fromisoformat(text)
    if pytype is bool:
        return text.lower() in {"true", "1", "t", "yes"}
    if pytype is int:
        return int(Decimal(text)) if "." in text else int(text)
    if pytype is float:
        return float(text)
    if pytype is Decimal:
        return Decimal(text)
    if pytype in (dict, list):
        return json.loads(text)
    return text


def _import_all_models() -> None:
    """Ensure every table is present in `Base.metadata` before discovery."""
    import app.modules.administration.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.brands.models  # noqa: F401
    import app.modules.categories.models  # noqa: F401
    import app.modules.customers.models  # noqa: F401
    import app.modules.delivery.models  # noqa: F401
    import app.modules.pos.models  # noqa: F401
    import app.modules.reports.models  # noqa: F401
    import app.modules.stock.models  # noqa: F401
    import app.modules.suppliers.models  # noqa: F401
    import app.shared.audit.models  # noqa: F401
    import app.shared.documents.models  # noqa: F401


def discover_tables(selected: list[str] | None = None) -> dict[str, Any]:
    """Return the backup-eligible tables keyed by name."""
    from app.core.database import Base

    _import_all_models()
    tables = {
        name: table
        for name, table in Base.metadata.tables.items()
        if name not in SKIPPED_TABLES
    }
    if selected:
        unknown = sorted(set(selected) - set(tables))
        if unknown:
            raise ValidationError(f"Unknown tables: {', '.join(unknown)}")
        tables = {name: tables[name] for name in selected}
    return dict(sorted(tables.items()))


def _pk_columns(table) -> list[str]:
    columns = [column.name for column in table.primary_key.columns]
    if not columns:
        raise ValidationError(f"Table '{table.name}' has no primary key and cannot be backed up")
    return columns


def _record_key(values: dict[str, Any], pk_columns: list[str]) -> str:
    """Stable, unique record id — composite for tables with a multi-column PK."""
    return "|".join(str(values.get(column) or "") for column in pk_columns)


def _data_columns(table) -> list[str]:
    return [column.name for column in table.columns]


# ------------------------------------------------------------------- config


async def load_config(session: AsyncSession) -> BackupConfig:
    from app.modules.administration.service import get_setting_value

    enabled = bool(await get_setting_value(session, "backup", "enabled", False))
    interval = int(await get_setting_value(session, "backup", "interval_hours", 24) or 24)
    if interval not in VALID_INTERVALS:
        interval = 24
    spreadsheet_id = str(await get_setting_value(session, "backup", "spreadsheet_id", "") or "").strip()
    service_account_json = str(
        await get_setting_value(session, "backup", "service_account_json", "") or ""
    ).strip()
    return BackupConfig(
        enabled=enabled,
        interval_hours=interval,
        spreadsheet_id=spreadsheet_id,
        service_account_json=service_account_json,
    )


def build_client(config: BackupConfig) -> SheetsClient:
    if not config.configured:
        raise SheetsError(
            "Google Sheets backup is not configured. Add a spreadsheet ID and "
            "service-account key in Settings first."
        )
    info = parse_service_account_json(config.service_account_json)
    return GSpreadSheetsClient(config.spreadsheet_id, info)


# ------------------------------------------------------------------- backup


async def _ensure_header(client: SheetsClient, title: str, data_columns: list[str]) -> list[str]:
    base = META_COLUMNS + [column for column in data_columns if column not in META_COLUMNS]
    existing = [str(value) for value in await client.get_header(title)]
    if not existing:
        await client.set_header(title, base)
        return base
    missing = [column for column in base if column not in existing]
    if missing:
        existing = existing + missing
        await client.set_header(title, existing)
    return existing


async def _backup_table(
    session: AsyncSession,
    repo: BackupRepository,
    client: SheetsClient,
    table,
    backup_version: int,
) -> int:
    table_name = table.name
    pk_columns = _pk_columns(table)
    data_columns = _data_columns(table)
    ledger = await repo.latest_ledger(table_name)

    result = await session.execute(
        select(table).order_by(*[table.c[column] for column in pk_columns])
    )
    rows = result.mappings().all()

    now = _now()
    changes: list[tuple[str, int, str, str, dict[str, Any]]] = []
    for row in rows:
        values = {column: row[column] for column in data_columns}
        record_id = _record_key(values, pk_columns)
        if not record_id:
            continue
        # Never leak secret system settings into a spreadsheet.
        if table_name == "system_settings" and values.get("is_secret"):
            values["value"] = SECRET_MASK
        digest = content_hash(values)
        previous = ledger.get(record_id)
        if previous is None:
            record_version, operation = 1, "INSERT"
        elif previous[1] != digest:
            record_version, operation = previous[0] + 1, "UPDATE"
        else:
            continue
        changes.append((record_id, record_version, operation, digest, values))

    await repo.upsert_table_state(
        table_name,
        last_version=backup_version,
        last_record_count=len(rows),
        backed_up_at=now,
        error=None,
    )

    # Keep the sheet header in sync with the schema even when no record changed,
    # so a newly added column is ready before the first value arrives.
    header = await _ensure_header(client, table_name, data_columns)
    if not changes:
        return 0

    sheet_rows: list[list[Any]] = []
    for record_id, record_version, operation, _digest, values in changes:
        row_map: dict[str, Any] = {
            "backup_at": now.isoformat(),
            "backup_version": backup_version,
            "table_name": table_name,
            "record_id": record_id,
            "operation": operation,
            "record_version": record_version,
        }
        for column in data_columns:
            row_map[column] = serialize(values.get(column))
        sheet_rows.append([row_map.get(column, "") for column in header])

    await client.append_rows(table_name, sheet_rows)

    from app.modules.backup.models import BackupRecord

    for record_id, record_version, operation, digest, _values in changes:
        # on_conflict_do_nothing keeps a concurrent run from failing the table
        # savepoint if it computed the same next version.
        await session.execute(
            pg_insert(BackupRecord)
            .values(
                table_name=table_name,
                record_id=record_id,
                version=record_version,
                backup_version=backup_version,
                operation=operation,
                content_hash=digest,
                backed_up_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=["table_name", "record_id", "version"]
            )
        )
    await session.flush()
    return len(changes)


async def run_backup(
    session: AsyncSession,
    *,
    trigger: str = "MANUAL",
    client: SheetsClient | None = None,
    tables: list[str] | None = None,
) -> dict:
    """Back up every (or selected) table. Never raises for per-table failures."""
    repo = BackupRepository(session)
    config = await load_config(session)
    if client is None:
        try:
            client = build_client(config)
        except SheetsError as exc:
            raise ValidationError(str(exc)) from exc

    selected = discover_tables(tables)
    job = await repo.create_job(trigger=trigger, spreadsheet_id=config.spreadsheet_id or None)
    await session.commit()

    backup_version = await repo.max_backup_version() + 1
    succeeded = failed = 0
    total_rows = 0
    errors: list[str] = []

    for table in selected.values():
        try:
            async with session.begin_nested():
                written = await _backup_table(session, repo, client, table, backup_version)
            succeeded += 1
            total_rows += written
        except Exception as exc:  # noqa: BLE001 - one bad table must not stop the rest
            failed += 1
            message = str(exc)
            errors.append(f"{table.name}: {message}")
            logger.exception("Backup failed for table %s", table.name)
            try:
                async with session.begin_nested():
                    await repo.upsert_table_state(
                        table.name,
                        last_version=backup_version,
                        last_record_count=0,
                        backed_up_at=_now(),
                        error=message[:2000],
                    )
            except Exception:  # noqa: BLE001
                logger.exception("Could not persist backup error for %s", table.name)

    job.tables_total = len(selected)
    job.tables_succeeded = succeeded
    job.tables_failed = failed
    job.rows_backed_up = total_rows
    job.finished_at = _now()
    job.error_message = "; ".join(errors)[:2000] or None
    job.status = "SUCCESS" if failed == 0 else ("PARTIAL" if succeeded else "FAILED")
    await session.commit()

    logger.info(
        "Google Sheets backup %s: tables=%s ok=%s failed=%s rows=%s",
        job.status,
        len(selected),
        succeeded,
        failed,
        total_rows,
    )
    return job_to_dict(job)


async def run_scheduled_backup() -> dict:
    """Entry point for the in-process scheduler — uses its own session."""
    from app.core.database import SessionFactory

    async with SessionFactory() as session:
        return await run_backup(session, trigger="SCHEDULED")


# ------------------------------------------------------------------ restore


def _cell(raw: list[Any], index: int) -> Any:
    return raw[index] if index < len(raw) else ""


async def _restore_table(
    session: AsyncSession,
    client: SheetsClient,
    table,
    *,
    dry_run: bool,
) -> dict:
    rows = await client.get_rows(table.name)
    summary = {"table": table.name, "records": 0, "inserted": 0, "updated": 0, "skipped": 0}
    if len(rows) < 2:
        return summary

    header = [str(value) for value in rows[0]]
    index = {column: position for position, column in enumerate(header)}
    if "record_id" not in index:
        raise ValidationError(f"Sheet '{table.name}' has no record_id column")
    db_columns = {column.name: column for column in table.columns}
    pk_columns = _pk_columns(table)

    # Keep only the newest version of each record (dedupe repeated backup rows).
    latest: dict[str, tuple[int, list[Any]]] = {}
    for raw in rows[1:]:
        record_id = str(_cell(raw, index["record_id"]) or "").strip()
        if not record_id:
            continue
        if "record_version" in index:
            try:
                version = int(Decimal(str(_cell(raw, index["record_version"]) or "0")))
            except Exception:  # noqa: BLE001
                version = 0
        else:
            version = 0
        if record_id not in latest or version >= latest[record_id][0]:
            latest[record_id] = (version, raw)

    for record_id, (_version, raw) in latest.items():
        data: dict[str, Any] = {}
        for column, position in index.items():
            if column in META_COLUMNS or column not in db_columns:
                continue
            data[column] = coerce(db_columns[column], _cell(raw, position))

        # Primary-key columns are always present in the sheet, but fall back to
        # the composite record_id if a key cell is missing.
        if any(data.get(column) in (None, "") for column in pk_columns):
            parts = record_id.split("|")
            if len(parts) == len(pk_columns):
                for column, part in zip(pk_columns, parts):
                    if data.get(column) in (None, ""):
                        data[column] = coerce(db_columns[column], part)
        if any(data.get(column) in (None, "") for column in pk_columns):
            summary["skipped"] += 1
            continue

        key_condition = and_(*[table.c[column] == data[column] for column in pk_columns])
        existing = await session.scalar(
            select(func.count()).select_from(table).where(key_condition)
        )
        if dry_run:
            summary["inserted" if not existing else "updated"] += 1
            summary["records"] += 1
            continue

        statement = pg_insert(table).values(**data)
        update_columns = {
            column: statement.excluded[column] for column in data if column not in pk_columns
        }
        if update_columns:
            statement = statement.on_conflict_do_update(
                index_elements=[table.c[column] for column in pk_columns], set_=update_columns
            )
        else:
            statement = statement.on_conflict_do_nothing(
                index_elements=[table.c[column] for column in pk_columns]
            )
        await session.execute(statement)
        summary["inserted" if not existing else "updated"] += 1
        summary["records"] += 1

    return summary


async def restore_backup(
    session: AsyncSession,
    *,
    tables: list[str] | None = None,
    dry_run: bool = False,
    confirm: bool = False,
    client: SheetsClient | None = None,
) -> dict:
    """Restore spreadsheet rows back into the database (upsert by primary key)."""
    if not confirm:
        raise ValidationError("Restore must be explicitly confirmed")
    config = await load_config(session)
    if client is None:
        try:
            client = build_client(config)
        except SheetsError as exc:
            raise ValidationError(str(exc)) from exc

    available = discover_tables(None)
    if tables:
        unknown = sorted(set(tables) - set(available))
        if unknown:
            raise ValidationError(f"Unknown tables: {', '.join(unknown)}")
        target = {name: available[name] for name in tables}
    else:
        tab_titles = set(await client.list_tabs())
        target = {name: table for name, table in available.items() if name in tab_titles}

    details: list[dict] = []
    totals = {"tables": 0, "records": 0, "inserted": 0, "updated": 0, "skipped": 0}
    for name, table in target.items():
        try:
            async with session.begin_nested():
                summary = await _restore_table(session, client, table, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 - report and continue with other tables
            logger.exception("Restore failed for table %s", name)
            details.append({"table": name, "error": str(exc)})
            continue
        details.append(summary)
        totals["tables"] += 1
        for key in ("records", "inserted", "updated", "skipped"):
            totals[key] += summary[key]

    if dry_run:
        await session.rollback()
    else:
        await session.commit()

    return {
        "dry_run": dry_run,
        "tables": totals["tables"],
        "records": totals["records"],
        "inserted": totals["inserted"],
        "updated": totals["updated"],
        "skipped": totals["skipped"],
        "details": details,
    }


# ------------------------------------------------------------------- status


def job_to_dict(job) -> dict:
    return {
        "id": str(job.id),
        "trigger": job.trigger,
        "status": job.status,
        "spreadsheet_id": job.spreadsheet_id,
        "tables_total": job.tables_total,
        "tables_succeeded": job.tables_succeeded,
        "tables_failed": job.tables_failed,
        "rows_backed_up": job.rows_backed_up,
        "error_message": job.error_message,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


async def get_status(session: AsyncSession) -> dict:
    repo = BackupRepository(session)
    config = await load_config(session)
    job = await repo.latest_job()
    states = await repo.list_table_states()
    return {
        "configured": config.configured,
        "enabled": config.enabled,
        "interval_hours": config.interval_hours,
        "spreadsheet_id": config.spreadsheet_id,
        "last_job": job_to_dict(job) if job else None,
        "tables": [
            {
                "table_name": state.table_name,
                "last_version": state.last_version,
                "last_backup_at": state.last_backup_at,
                "last_record_count": state.last_record_count,
                "last_error": state.last_error,
            }
            for state in states
        ],
    }
