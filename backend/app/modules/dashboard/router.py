"""Dashboard endpoints — spec section 2.1.1 (API only, no UI in this phase)."""

import json
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import envelope, get_db_session, require_permission
from app.core.config import settings
from app.core.redis import cache
from app.modules.auth.models import User
from app.modules.dashboard.schemas import DashboardOut, Envelope
from app.modules.dashboard.service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Short-lived cache matching the documented dashboard cache. Enabled outside
# debug/test runs so a test that creates data then re-reads the summary still
# sees fresh numbers; production (DEBUG=false) gets the ~60 s cache.
_CACHE_ENABLED = settings.dashboard_cache_ttl_seconds > 0 and not settings.debug


@router.get("/summary", response_model=Envelope[DashboardOut])
async def dashboard_summary(
    period: str = Query(default="7d", pattern="^(7d|month|custom)$"),
    start_date: date | None = Query(default=None, alias="startDate"),
    end_date: date | None = Query(default=None, alias="endDate"),
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission("dashboard.view")),
) -> dict:
    cache_key = (
        f"dashboard:summary:{actor.id}:{period}:{start_date}:{end_date}:{actor.token_version}"
    )
    if _CACHE_ENABLED:
        cached = await cache.get(cache_key)
        if cached:
            try:
                return envelope(DashboardOut.model_validate(json.loads(cached)))
            except Exception:
                pass
    service = DashboardService(db)
    data = await service.summary(period=period, start=start_date, end=end_date, actor=actor)
    output = DashboardOut.model_validate(data)
    if _CACHE_ENABLED:
        await cache.set(
            cache_key,
            json.dumps(output.model_dump(mode="json")),
            settings.dashboard_cache_ttl_seconds,
        )
    return envelope(output)
