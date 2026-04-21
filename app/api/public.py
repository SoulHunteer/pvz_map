"""Public (no-auth) API endpoints used by the marketing landing page.

All responses here should be anonymized and safe to expose to anonymous visitors.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import select

from app.db.models import (
    AvitoChangeEvent,
    AvitoEventType,
    AvitoWatch,
    ChangeEvent,
    ChangeEventType,
    TrackedItem,
)
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

public_router = APIRouter(tags=["public"])


# ── utils ────────────────────────────────────────────────────────────

def _truncate(text: str | None, max_len: int = 40) -> str:
    if not text:
        return ""
    text = text.strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def _relative_time(now: datetime, ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return "только что"
    mins = secs // 60
    if mins < 60:
        return f"{mins} мин назад"
    hours = mins // 60
    if hours < 24:
        return f"{hours} ч назад"
    days = hours // 24
    return f"{days} дн назад"


# ── event mappers ────────────────────────────────────────────────────

_AVITO_DOT = {
    AvitoEventType.NEW_LISTINGS: "green",
    AvitoEventType.PRICE_CHANGED: "gold",
    AvitoEventType.LISTINGS_REMOVED: "purple",
}

_WB_DOT = {
    ChangeEventType.NEW_ZONES: "gold",
    ChangeEventType.ZONES_REMOVED: "purple",
    ChangeEventType.ZONES_MODIFIED: "gold",
    ChangeEventType.CHANGED: "gold",
    ChangeEventType.RESTORED: "green",
    ChangeEventType.BECAME_EMPTY: "purple",
}


def _format_avito_event(ev: AvitoChangeEvent, watch_title: str | None) -> dict | None:
    """Turn AvitoChangeEvent into a landing-friendly dict or None if uninteresting."""
    title = _truncate(watch_title) or "зона"

    # Parse details_json to extract one representative item
    sample_price = None
    sample_title = None
    if ev.details_json:
        try:
            details = json.loads(ev.details_json)
        except (ValueError, TypeError):
            details = {}
        for key in ("new", "price_changed", "removed"):
            items = details.get(key) or []
            if items:
                first = items[0]
                sample_title = _truncate(first.get("title"), 50)
                sample_price = first.get("price") or first.get("new_price") or first.get("old_price")
                break

    et = ev.event_type
    if et == AvitoEventType.NEW_LISTINGS:
        text = f"Новое объявление · {title}"
        if ev.new_count > 1:
            text = f"Новые объявления ({ev.new_count}) · {title}"
        if sample_price:
            text += f" · {sample_price}"
    elif et == AvitoEventType.PRICE_CHANGED:
        text = f"Изменение цены · {title}"
        if ev.price_changed_count > 1:
            text = f"Изменение цен ({ev.price_changed_count}) · {title}"
    elif et == AvitoEventType.LISTINGS_REMOVED:
        text = f"Объявление снято · {title}"
        if ev.removed_count > 1:
            text = f"Сняты объявления ({ev.removed_count}) · {title}"
    else:
        return None

    return {
        "dot": _AVITO_DOT.get(et, "gold"),
        "text": text,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


def _format_wb_event(ev: ChangeEvent, item_title: str | None) -> dict | None:
    title = _truncate(item_title) or "зона"
    et = ev.event_type
    if et == ChangeEventType.NEW_ZONES:
        text = f"Новые зоны WB ({ev.added_count}) · {title}"
    elif et == ChangeEventType.ZONES_REMOVED:
        text = f"Убрали зоны ({ev.removed_count}) · {title}"
    elif et == ChangeEventType.ZONES_MODIFIED:
        text = f"Изменение зон · {title}"
    elif et == ChangeEventType.CHANGED:
        parts = []
        if ev.added_count:
            parts.append(f"+{ev.added_count}")
        if ev.removed_count:
            parts.append(f"−{ev.removed_count}")
        suffix = f" ({', '.join(parts)})" if parts else ""
        text = f"Обновление зон WB{suffix} · {title}"
    elif et == ChangeEventType.RESTORED:
        text = f"Зоны вернулись · {title}"
    elif et == ChangeEventType.BECAME_EMPTY:
        text = f"Зоны исчезли · {title}"
    else:
        return None
    return {
        "dot": _WB_DOT.get(et, "gold"),
        "text": text,
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


# ── data loader (runs in thread) ─────────────────────────────────────

def _load_recent_events(limit: int, hours: int = 24) -> list[dict]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    events: list[tuple[datetime, dict]] = []

    with SessionLocal() as session:
        # Avito events + their watch title
        avito_stmt = (
            select(AvitoChangeEvent, AvitoWatch.title)
            .join(AvitoWatch, AvitoChangeEvent.avito_watch_id == AvitoWatch.id)
            .where(AvitoChangeEvent.created_at >= since)
            .order_by(AvitoChangeEvent.created_at.desc())
            .limit(limit * 3)
        )
        for ev, watch_title in session.execute(avito_stmt).all():
            formatted = _format_avito_event(ev, watch_title)
            if formatted:
                events.append((ev.created_at, formatted))

        # WB zone events + their tracked item title
        wb_stmt = (
            select(ChangeEvent, TrackedItem.title)
            .join(TrackedItem, ChangeEvent.tracked_item_id == TrackedItem.id)
            .where(ChangeEvent.created_at >= since)
            .order_by(ChangeEvent.created_at.desc())
            .limit(limit * 3)
        )
        for ev, item_title in session.execute(wb_stmt).all():
            formatted = _format_wb_event(ev, item_title)
            if formatted:
                events.append((ev.created_at, formatted))

    # Sort merged list by created_at desc, fill relative labels, take top N
    events.sort(key=lambda pair: pair[0] or since, reverse=True)
    result: list[dict] = []
    for ts, formatted in events[:limit]:
        formatted = dict(formatted)
        formatted["time_label"] = _relative_time(now, ts) if ts else ""
        result.append(formatted)
    return result


# ── endpoints ────────────────────────────────────────────────────────

@public_router.get("/api/public/recent-events")
async def get_public_recent_events(limit: int = 12) -> dict:
    """Recent monitoring events (last 24h), anonymized. Used by the landing page."""
    safe_limit = max(1, min(limit, 30))
    try:
        events = await asyncio.to_thread(_load_recent_events, safe_limit)
    except Exception:
        logger.exception("Failed to load public recent events")
        events = []
    return {"events": events}
