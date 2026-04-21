"""Generate a static showcase map PNG for the public landing page.

Picks a real TrackedItem with recent activity, fetches its current WB zones
and offices (plus Avito listings if available), renders the notification map,
and publishes the PNG to ``data/public/showcase-map.png`` — served by the
backend at ``/artifacts/public/showcase-map.png``.

Run standalone::

    python -m scripts.generate_showcase_map
    python -m scripts.generate_showcase_map --item-id 42
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from app.core import get_settings, setup_logging
from app.db.models import TrackedItem
from app.db.repositories import TrackedItemRepository
from app.db.repositories.avito import AvitoListingRepository, AvitoWatchRepository
from app.db.session import SessionLocal
from app.services.geo_utils import extract_coordinates
from app.services.map_renderer import save_notification_assets
from app.services.wb_zone_fetcher import fetch_zones

logger = logging.getLogger("scripts.generate_showcase_map")


def _pick_item(session, preferred_id: int | None) -> TrackedItem | None:
    repo = TrackedItemRepository(session)
    if preferred_id is not None:
        item = session.get(TrackedItem, preferred_id)
        if item is None:
            logger.error("Tracked item %s not found", preferred_id)
        return item

    items = repo.list_active()
    if not items:
        logger.warning("No active tracked items — cannot build showcase map")
        return None

    # Prefer items that have an Avito watch (richer picture), fall back to
    # whichever item has the highest last_zone_count.
    watch_repo = AvitoWatchRepository(session)
    with_avito: list[TrackedItem] = []
    for it in items:
        if watch_repo.get_by_tracked_item(it.id) is not None:
            with_avito.append(it)

    pool = with_avito or items
    pool.sort(key=lambda it: (it.last_zone_count or 0), reverse=True)
    return pool[0]


def _build_listings(session, tracked_item_id: int) -> list[dict]:
    watch_repo = AvitoWatchRepository(session)
    watch = watch_repo.get_by_tracked_item(tracked_item_id)
    if watch is None:
        return []
    listing_repo = AvitoListingRepository(session)
    listings = listing_repo.list_active_for_watch(watch.id)
    return [
        {
            "lat": al.lat,
            "lng": al.lng,
            "title": al.title,
            "price": al.price,
            "area_m2": al.area_m2,
            "address": al.address,
            "listing_url": al.listing_url,
            "avito_id": al.avito_listing_id,
            "status": al.status.value if al.status else "seen",
        }
        for al in listings
        if al.lat is not None and al.lng is not None
    ]


def _build_offices(wb_offices) -> list[dict]:
    return [
        {
            "office_id": o.office_id,
            "lat": o.lat,
            "lng": o.lng,
            "area_m2": o.area_m2,
            "loading": o.loading,
            "loading_level": o.loading_level,
            "free_capacity_pct": o.free_capacity_pct,
            "rating": o.rating,
            "type_label": o.type_label,
            "type_point": o.type_point,
            "is_highloading": o.is_highloading,
            "is_open_in_future": o.is_open_in_future,
        }
        for o in wb_offices
    ]


def generate(item_id: int | None = None) -> Path | None:
    settings = get_settings()
    setup_logging(settings)

    with SessionLocal() as session:
        item = _pick_item(session, item_id)
        if item is None:
            return None

        try:
            coords = extract_coordinates(item.map_link)
        except ValueError as exc:
            logger.error("Bad map_link on item %s: %s", item.id, exc)
            return None

        logger.info(
            "Showcase item id=%s title=%r center=(%.4f, %.4f) zoom=%.1f",
            item.id, item.title, coords.lat, coords.lng, coords.zoom,
        )

        wb_result = fetch_zones(coords)
        if not wb_result.ok:
            logger.error("WB fetch failed: %s", wb_result.error)
            return None

        zones = wb_result.zones
        offices = _build_offices(wb_result.offices)
        listings = _build_listings(session, item.id)
        logger.info(
            "Fetched %d zones, %d offices, %d avito listings",
            len(zones), len(offices), len(listings),
        )

        # Use a fixed snapshot_id so the path is stable between runs.
        img_path_str, _html_path_str = save_notification_assets(
            coords=coords,
            zones=zones,
            zone_statuses=None,
            listings=listings,
            offices=offices,
            tracked_item_id=item.id,
            snapshot_id=0,
        )

    src = Path(img_path_str)
    if not src.exists():
        logger.error("Rendered image missing: %s", src)
        return None

    public_dir = settings.artifact_root / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    dst = public_dir / "showcase-map.png"
    shutil.copyfile(src, dst)
    logger.info("Showcase map published: %s", dst)
    return dst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--item-id",
        type=int,
        default=None,
        help="Override: TrackedItem id to render. If omitted, picks automatically.",
    )
    args = parser.parse_args(argv)
    result = generate(args.item_id)
    return 0 if result is not None else 1


if __name__ == "__main__":
    sys.exit(main())
