from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import AuthContext, get_auth_context, get_mvp_service
from app.api.schemas import ManualCheckResponse, TrackedItemCreateRequest, TrackedItemPatchRequest
from app.core.exceptions import AccessDeniedError, NotFoundError, TariffLimitError, ValidationError
from app.services.mvp import MvpService

router = APIRouter(tags=["mvp"])


def _raise_http_for_domain_error(exc: Exception) -> None:
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, AccessDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, TariffLimitError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, ValidationError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "component": "backend-api"}


@router.get("/api/me")
async def get_me(auth: AuthContext = Depends(get_auth_context)) -> dict:
    return auth.summary


@router.get("/api/tracked-items")
async def list_tracked_items(
    auth: AuthContext = Depends(get_auth_context),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> list[dict]:
    return await asyncio.to_thread(mvp_service.list_tracked_items, auth.telegram_user_id)


@router.post("/api/tracked-items")
async def create_tracked_item(
    payload: TrackedItemCreateRequest,
    auth: AuthContext = Depends(get_auth_context),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> dict:
    try:
        item = await asyncio.to_thread(
            mvp_service.create_tracked_item,
            auth.telegram_user_id,
            payload.map_link,
            payload.title,
            auth.username,
            auth.full_name,
            payload.is_active,
        )

        check_result = None
        if payload.run_initial_check:
            check_result = await asyncio.to_thread(mvp_service.run_manual_check, auth.telegram_user_id, item["id"])

        return {"item": item, "initial_check": check_result}
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.get("/api/tracked-items/{tracked_item_id}")
async def get_tracked_item(
    tracked_item_id: int,
    auth: AuthContext = Depends(get_auth_context),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> dict:
    try:
        return await asyncio.to_thread(mvp_service.get_item_full_details, auth.telegram_user_id, tracked_item_id)
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.post("/api/tracked-items/{tracked_item_id}/check", response_model=ManualCheckResponse)
async def manual_check_tracked_item(
    tracked_item_id: int,
    auth: AuthContext = Depends(get_auth_context),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> ManualCheckResponse:
    try:
        result = await asyncio.to_thread(mvp_service.run_manual_check, auth.telegram_user_id, tracked_item_id)
        return ManualCheckResponse(**result)
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.patch("/api/tracked-items/{tracked_item_id}")
async def patch_tracked_item(
    tracked_item_id: int,
    payload: TrackedItemPatchRequest,
    auth: AuthContext = Depends(get_auth_context),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> dict:
    try:
        return await asyncio.to_thread(
            mvp_service.update_tracked_item,
            auth.telegram_user_id,
            tracked_item_id,
            title=payload.title,
            map_link=payload.map_link,
            is_active=payload.is_active,
        )
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.delete("/api/tracked-items/{tracked_item_id}")
async def delete_tracked_item(
    tracked_item_id: int,
    auth: AuthContext = Depends(get_auth_context),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> dict:
    try:
        await asyncio.to_thread(mvp_service.delete_tracked_item, auth.telegram_user_id, tracked_item_id)
        return {"deleted": True, "tracked_item_id": tracked_item_id}
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.get("/api/tracked-items/{tracked_item_id}/snapshots")
async def list_item_snapshots(
    tracked_item_id: int,
    limit: int = 10,
    auth: AuthContext = Depends(get_auth_context),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> list[dict]:
    safe_limit = max(1, min(limit, 100))
    try:
        return await asyncio.to_thread(mvp_service.list_item_snapshots, auth.telegram_user_id, tracked_item_id, safe_limit)
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise


@router.get("/api/tracked-items/{tracked_item_id}/events")
async def list_item_events(
    tracked_item_id: int,
    limit: int = 10,
    auth: AuthContext = Depends(get_auth_context),
    mvp_service: MvpService = Depends(get_mvp_service),
) -> list[dict]:
    safe_limit = max(1, min(limit, 100))
    try:
        return await asyncio.to_thread(mvp_service.list_item_events, auth.telegram_user_id, tracked_item_id, safe_limit)
    except Exception as exc:
        _raise_http_for_domain_error(exc)
        raise

