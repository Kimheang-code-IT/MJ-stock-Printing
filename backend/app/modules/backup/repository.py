from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.backup.models import BackupJob, BackupRecord, BackupTableState


class BackupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ jobs

    async def create_job(self, *, trigger: str, spreadsheet_id: str | None) -> BackupJob:
        job = BackupJob(
            trigger=trigger,
            status="RUNNING",
            spreadsheet_id=spreadsheet_id,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def latest_job(self) -> BackupJob | None:
        result = await self.session.execute(
            select(BackupJob).order_by(BackupJob.started_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_jobs(self, *, page: int, limit: int) -> tuple[list[BackupJob], int]:
        total = (await self.session.execute(select(func.count()).select_from(BackupJob))).scalar_one()
        rows = await self.session.execute(
            select(BackupJob).order_by(BackupJob.started_at.desc()).offset((page - 1) * limit).limit(limit)
        )
        return list(rows.scalars().all()), int(total)

    # ----------------------------------------------------------- table state

    async def get_table_state(self, table_name: str) -> BackupTableState | None:
        return await self.session.get(BackupTableState, table_name)

    async def list_table_states(self) -> list[BackupTableState]:
        rows = await self.session.execute(
            select(BackupTableState).order_by(BackupTableState.table_name)
        )
        return list(rows.scalars().all())

    async def upsert_table_state(
        self,
        table_name: str,
        *,
        last_version: int,
        last_record_count: int,
        backed_up_at: datetime,
        error: str | None,
    ) -> None:
        state = await self.session.get(BackupTableState, table_name)
        if state is None:
            state = BackupTableState(table_name=table_name)
            self.session.add(state)
        state.last_version = last_version
        state.last_record_count = last_record_count
        state.last_backup_at = backed_up_at
        state.last_error = error

    # --------------------------------------------------------------- ledger

    async def latest_ledger(self, table_name: str) -> dict[str, tuple[int, str]]:
        """Latest `(version, content_hash)` per record for one table."""
        rows = await self.session.execute(
            select(BackupRecord.record_id, BackupRecord.version, BackupRecord.content_hash)
            .where(BackupRecord.table_name == table_name)
            .order_by(BackupRecord.record_id, BackupRecord.version.desc())
            .distinct(BackupRecord.record_id)
        )
        return {record_id: (version, content_hash) for record_id, version, content_hash in rows.all()}

    async def max_backup_version(self) -> int:
        value = (await self.session.execute(select(func.max(BackupRecord.backup_version)))).scalar()
        return int(value or 0)
