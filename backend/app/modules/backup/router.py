"""Google Sheets backup API (`/api/v1/backups/*`)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import envelope, get_db_session, require_permission
from app.modules.auth.models import User
from app.modules.backup import service as backup_service
from app.modules.backup.schemas import BackupRestoreRequest, BackupRunRequest

router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("/status")
async def backup_status(
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("settings.view")),
) -> dict:
    return envelope(await backup_service.get_status(db))


@router.get("/jobs")
async def list_backup_jobs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("settings.view")),
) -> dict:
    from app.modules.backup.repository import BackupRepository
    from app.shared.pagination.params import list_meta

    jobs, total = await BackupRepository(db).list_jobs(page=page, limit=limit)
    return envelope([backup_service.job_to_dict(job) for job in jobs], list_meta(page, limit, total))


@router.post("/test-connection")
async def test_backup_connection(
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("backup.run")),
) -> dict:
    """Validate the stored credentials without backing anything up."""
    from app.modules.backup.sheets import SheetsError

    config = await backup_service.load_config(db)
    if not config.configured:
        return envelope(
            {"status": "disabled", "message": "Add a spreadsheet ID and service-account key first."}
        )
    try:
        client = backup_service.build_client(config)
        tabs = await client.list_tabs()
    except SheetsError as exc:
        return envelope({"status": "failed", "message": str(exc)})
    return envelope(
        {"status": "connected", "message": f"Connected. {len(tabs)} tab(s) found."}
    )


@router.post("/run")
async def run_backup_now(
    payload: BackupRunRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("backup.run")),
) -> dict:
    """Run a manual backup immediately (in the request's own session)."""
    tables = (payload.tables if payload else None) or None
    return envelope(await backup_service.run_backup(db, trigger="MANUAL", tables=tables))


@router.post("/restore")
async def restore_backup_data(
    payload: BackupRestoreRequest,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("backup.restore")),
) -> dict:
    """Restore spreadsheet rows into the database (upsert by primary key)."""
    result = await backup_service.restore_backup(
        db,
        tables=payload.tables,
        dry_run=payload.dry_run,
        confirm=payload.confirm,
    )
    return envelope(result)
