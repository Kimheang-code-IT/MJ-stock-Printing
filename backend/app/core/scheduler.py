"""In-process scheduler. Runs inside the FastAPI API process — not a Docker service.

The daily Telegram summary sleeps until the configured UTC hour, then runs in
this same process. A short Redis lock keeps a duplicate run from firing if more
than one API worker is started later. No Celery beat, no extra container.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings

logger = logging.getLogger("mj.scheduler")

LOCK_KEY = "mj:scheduler:daily_summary"
LOCK_TTL_SECONDS = 3600

BACKUP_LOCK_KEY = "mj:scheduler:backup"
BACKUP_LOCK_TTL_SECONDS = 3600
# How often the backup loop wakes to check whether the interval has elapsed.
BACKUP_POLL_SECONDS = 60


def seconds_until_next_scan(now: datetime | None = None) -> float:
    """Seconds until the next daily run at `daily_summary_scan_hour` UTC."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    hour = max(0, min(23, int(settings.daily_summary_scan_hour)))
    target = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
    if moment >= target:
        target += timedelta(days=1)
    return max(1.0, (target - moment).total_seconds())


async def run_daily_summary_once() -> dict:
    """Telegram daily summary at the configured local time. Never raises into
    the loop."""
    from app.core.database import SessionFactory
    from app.shared.telegram.service import send_daily_summary

    async with SessionFactory() as session:
        return await send_daily_summary(session)


async def _acquired_scan_lock() -> bool:
    return await _acquire_lock(LOCK_KEY, LOCK_TTL_SECONDS)


async def _acquire_lock(key: str, ttl_seconds: int) -> bool:
    try:
        from app.core.redis import get_redis

        redis = get_redis()
        return bool(await redis.set(key, "1", nx=True, ex=ttl_seconds))
    except Exception as exc:
        logger.warning("Scheduler lock unavailable (%s); running in this process", exc)
        return True


async def scheduler_loop(stop: asyncio.Event) -> None:
    logger.info(
        "In-process scheduler started (daily summary at %02d:00 UTC)",
        max(0, min(23, int(settings.daily_summary_scan_hour))),
    )
    while not stop.is_set():
        wait = seconds_until_next_scan()
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
            break
        except TimeoutError:
            pass
        if stop.is_set():
            break
        if not await _acquired_scan_lock():
            logger.info("Daily summary skipped: another API process holds the lock")
            continue
        try:
            summary_result = await run_daily_summary_once()
            if summary_result.get("enabled"):
                logger.info("Telegram daily summary: sent=%s", summary_result.get("sent"))
        except Exception:
            logger.exception("Telegram daily summary failed")


async def _backup_due() -> bool:
    """True when backup is enabled, configured and the interval has elapsed."""
    from app.core.database import SessionFactory
    from app.modules.backup.repository import BackupRepository
    from app.modules.backup.service import load_config

    async with SessionFactory() as session:
        config = await load_config(session)
        if not config.enabled or not config.configured:
            return False
        job = await BackupRepository(session).latest_job()

    if job is None:
        return True
    last_at = job.finished_at or job.started_at
    if last_at is None:
        return True
    if last_at.tzinfo is None:
        last_at = last_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_at >= timedelta(hours=config.interval_hours)


async def backup_loop(stop: asyncio.Event) -> None:
    logger.info("Google Sheets backup scheduler started")
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=BACKUP_POLL_SECONDS)
            break
        except TimeoutError:
            pass
        if stop.is_set():
            break
        try:
            due = await _backup_due()
        except Exception:
            logger.exception("Could not evaluate the Google Sheets backup schedule")
            continue
        if not due:
            continue
        if not await _acquire_lock(BACKUP_LOCK_KEY, BACKUP_LOCK_TTL_SECONDS):
            logger.info("Backup skipped: another API process holds the lock")
            continue
        try:
            from app.modules.backup.service import run_scheduled_backup

            result = await run_scheduled_backup()
            logger.info("Scheduled Google Sheets backup: %s", result.get("status"))
        except Exception:
            logger.exception("Scheduled Google Sheets backup failed")


def start_backend_scheduler() -> tuple[asyncio.Event, list[asyncio.Task[None]]]:
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(scheduler_loop(stop), name="mj-scheduler"),
        asyncio.create_task(backup_loop(stop), name="mj-backup-scheduler"),
    ]
    return stop, tasks
