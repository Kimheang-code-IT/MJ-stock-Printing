"""Telegram account linking (`/link CODE`).

The user generates a one-time code in the app (POST /auth/telegram/link-code,
or the forgot-password flow when no chat is linked) and sends it to the bot.
The bot consumes the code and binds its chat to the user account. This is the
only PostgreSQL write the bot process performs, and it only ever sets
`telegram_chat_id` / `telegram_verified` on the user named by the code. A code
created by the forgot-password flow also triggers a reset-code delivery.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.modules.auth.models import User

logger = logging.getLogger("stock_pos.telegram")

TELEGRAM_LINK_PREFIX = "tglink"  # must match app.modules.auth.service


async def consume_link_code(session: AsyncSession, code: str, chat_id: str) -> User | None:
    """Bind `chat_id` to the user identified by a valid, unexpired code.

    Returns the linked user, or None when the code is unknown/expired.
    The code is single use — it is deleted before the DB write. A code created
    by the forgot-password flow carries `reset: true`; after linking, a reset
    code is generated and sent to the chat.
    """
    normalized = (code or "").strip().upper()
    if not normalized or not chat_id:
        return None
    client = get_redis()
    try:
        raw = await client.get(f"{TELEGRAM_LINK_PREFIX}:{normalized}")
    except Exception as exc:
        logger.error("Failed to read telegram link code: %s", exc)
        return None
    if not raw:
        return None
    try:
        await client.delete(f"{TELEGRAM_LINK_PREFIX}:{normalized}")
        payload = json.loads(raw)
        user_id = payload["user_id"]
        reset_requested = bool(payload.get("reset"))
    except Exception as exc:
        logger.error("Failed to consume telegram link code: %s", exc)
        return None

    user = await session.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        return None
    user.telegram_chat_id = str(chat_id)
    user.telegram_verified = True
    await session.commit()
    if reset_requested:
        await _deliver_reset_code(session, user, str(chat_id))
    return user


async def _deliver_reset_code(session: AsyncSession, user: User, chat_id: str) -> None:
    """Issue a password-reset code for a freshly linked user and send it.

    Best effort: failures are logged and never bubble into the bot reply.
    """
    from app.core.config import settings
    from app.modules.auth.service import AuthService
    from app.shared.telegram.client import send_message
    from app.shared.telegram.delivery import RESET_CODE_TEXT, RESET_LINK_TEXT

    try:
        code, ttl_minutes, handoff_token = await AuthService(session).issue_reset_code(user)
    except Exception as exc:
        logger.error("Failed to issue reset code after telegram link: %s", exc)
        return
    text = RESET_CODE_TEXT.format(code=code, minutes=ttl_minutes)
    if handoff_token and settings.frontend_base_url:
        base = settings.frontend_base_url.rstrip("/")
        text += "\n" + RESET_LINK_TEXT.format(
            link=f"{base}/auth/reset-password?handoff={handoff_token}"
        )
    try:
        await send_message(chat_id, text)
    except Exception:
        logger.exception("Failed to send reset code to chat %s", chat_id)
