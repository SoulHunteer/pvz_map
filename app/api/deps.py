from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.core.exceptions import AccessDeniedError
from app.core.settings import Settings, get_settings
from app.services.mvp import MvpService


@dataclass(slots=True)
class AuthContext:
    telegram_user_id: int
    username: str | None
    full_name: str | None
    summary: dict


def get_mvp_service(request: Request) -> MvpService:
    service = getattr(request.app.state, "mvp_service", None)
    if service is None:
        raise RuntimeError("MvpService is not configured on app state")
    return service


def get_settings_dep() -> Settings:
    return get_settings()


async def get_auth_context(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> AuthContext:
    if not settings.dev_auth_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Auth disabled by configuration")

    raw_id = request.headers.get("X-Dev-Telegram-Id")
    if not raw_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Dev-Telegram-Id header",
        )

    try:
        telegram_user_id = int(raw_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid X-Dev-Telegram-Id") from exc

    allowed_user_ids = settings.allowed_telegram_user_ids
    if allowed_user_ids and telegram_user_id not in allowed_user_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not allowed in current test mode")

    username = request.headers.get("X-Dev-Username")
    full_name = request.headers.get("X-Dev-Full-Name")

    try:
        summary = mvp_service.get_or_create_user_summary(
            telegram_user_id=telegram_user_id,
            username=username,
            full_name=full_name,
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return AuthContext(
        telegram_user_id=telegram_user_id,
        username=username,
        full_name=full_name,
        summary=summary,
    )

