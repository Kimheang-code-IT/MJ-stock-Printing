from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import envelope, get_current_user, get_db_session
from app.core.config import settings
from app.core.exceptions import RateLimitedError
from app.core.rate_limit import RateLimited, enforce_rate_limit
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResetRequest,
    ForgotPasswordResponse,
    HandoffExchangeRequest,
    HandoffExchangeResponse,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    ProfileAvatarRequest,
    RefreshRequest,
    ResendResetCodeRequest,
    ResetPasswordRequest,
    SetupRequest,
    SetupStatusResponse,
    TelegramLinkCodeResponse,
    VerifyResetCodeRequest,
    VerifyResetCodeResponse,
    auth_user_payload,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_RESET_MESSAGE = (
    "If the email exists and Telegram delivery is configured, a verification code has been sent."
)


def _client_ip(request: Request) -> str | None:
    # Prefer the header our own reverse proxy sets ($remote_addr). Do NOT trust
    # the first X-Forwarded-For entry: nginx appends the real client to any
    # client-supplied value, so the first entry is spoofable and would let an
    # attacker rotate the rate-limit key. The last entry is the closest peer.
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else None


@router.get("/setup/status", response_model=None)
async def setup_status(db: AsyncSession = Depends(get_db_session)) -> dict:
    service = AuthService(db)
    return envelope(SetupStatusResponse(setup_completed=await service.setup_completed()))


@router.post("/setup", response_model=None, status_code=201)
async def setup(
    payload: SetupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    service = AuthService(db)
    user = await service.setup(
        payload, ip_address=_client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return envelope({"message": "Initial setup completed. You can now log in.", "user": user})


@router.post("/login", response_model=None)
async def login(
    payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db_session)
) -> dict:
    service = AuthService(db)
    tokens = await service.login(
        payload, ip_address=_client_ip(request), user_agent=request.headers.get("user-agent")
    )
    return envelope(tokens)


@router.post("/refresh", response_model=None)
async def refresh(payload: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db_session)) -> dict:
    try:
        await enforce_rate_limit(
            f"refresh:{_client_ip(request)}",
            settings.rate_limit_refresh_per_minute,
            60,
        )
    except RateLimited:
        raise RateLimitedError("Too many refresh attempts. Try again later.")
    service = AuthService(db)
    return envelope(await service.refresh(payload.refresh_token))


@router.post("/logout", response_model=None)
async def logout(
    payload: LogoutRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = AuthService(db)
    await service.logout(current_user, payload.refresh_token)
    return envelope(MessageResponse(message="Logged out"))


@router.post("/forgot-password", response_model=None)
async def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db_session)
) -> dict:
    service = AuthService(db)
    result = await service.forgot_password(payload.email, ip_address=_client_ip(request))
    return envelope(ForgotPasswordResponse(**result))


@router.post("/verify-reset-code", response_model=None)
async def verify_reset_code(
    payload: VerifyResetCodeRequest, db: AsyncSession = Depends(get_db_session)
) -> dict:
    service = AuthService(db)
    reset_token, expires_in = await service.verify_reset_code(payload.email, payload.code)
    return envelope(VerifyResetCodeResponse(reset_token=reset_token, resetToken=reset_token, expires_in=expires_in, expiresIn=expires_in))


@router.post("/forgot-password/verify", response_model=None)
async def verify_reset_code_frontend(
    payload: VerifyResetCodeRequest, db: AsyncSession = Depends(get_db_session)
) -> dict:
    """Frontend path for code verification (same flow as /verify-reset-code)."""
    return await verify_reset_code(payload, db=db)


@router.post("/forgot-password/resend", response_model=None)
async def resend_reset_code(
    payload: ResendResetCodeRequest, request: Request, db: AsyncSession = Depends(get_db_session)
) -> dict:
    """Re-send the verification code through Telegram (or re-issue the bot link
    code when the account has no linked chat yet)."""
    service = AuthService(db)
    result = await service.forgot_password(payload.email, ip_address=_client_ip(request))
    return envelope(ForgotPasswordResponse(**result))


@router.post("/reset-password", response_model=None)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db_session)) -> dict:
    service = AuthService(db)
    await service.reset_password(payload.reset_token, payload.new_password)
    return envelope(MessageResponse(message="Password has been reset. You can now log in."))


@router.post("/forgot-password/reset", response_model=None)
async def reset_password_frontend(
    payload: ForgotPasswordResetRequest, db: AsyncSession = Depends(get_db_session)
) -> dict:
    """Frontend reset path (camelCase body: resetToken/newPassword)."""
    service = AuthService(db)
    await service.reset_password(payload.reset_token, payload.new_password)
    return envelope(MessageResponse(message="Password has been reset. You can now log in."))


@router.post("/forgot-password/handoff", response_model=None)
async def exchange_reset_handoff(
    payload: HandoffExchangeRequest, db: AsyncSession = Depends(get_db_session)
) -> dict:
    """Exchange a Telegram deep-link handoff token for an email + reset token
    (the reset-password page consumes this when opened from Telegram)."""
    service = AuthService(db)
    user, reset_token, expires_in = await service.exchange_handoff(payload.handoff)
    return envelope(
        HandoffExchangeResponse(
            email=user.email,
            reset_token=reset_token,
            resetToken=reset_token,
            expires_in=expires_in,
            expiresIn=expires_in,
        )
    )


@router.post("/change-password", response_model=None)
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Authenticated self-service password change (signs out other sessions)."""
    service = AuthService(db)
    await service.change_password(current_user, payload.current_password, payload.new_password)
    return envelope(MessageResponse(message="Password changed"))


@router.patch("/profile/avatar", response_model=None)
async def update_profile_avatar(
    payload: ProfileAvatarRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = AuthService(db)
    user = await service.update_avatar(current_user, payload.avatar)
    return envelope(auth_user_payload(user))


@router.post("/telegram/link-code", response_model=None)
async def create_telegram_link_code(
    db: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """One-time code the user sends to the bot (`/link CODE`) to bind this
    chat to their account."""
    service = AuthService(db)
    code, expires_in = await service.create_telegram_link_code(current_user)
    return envelope(
        TelegramLinkCodeResponse(code=code, expires_in=expires_in, expiresIn=expires_in)
    )


@router.get("/me", response_model=None)
async def me(
    current_user: User = Depends(get_current_user),
) -> dict:
    return envelope(auth_user_payload(current_user))
