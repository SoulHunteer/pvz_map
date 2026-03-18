from __future__ import annotations

from pydantic import BaseModel, Field


class TrackedItemCreateRequest(BaseModel):
    title: str | None = None
    map_link: str = Field(min_length=5)
    is_active: bool = False
    run_initial_check: bool = True


class TrackedItemPatchRequest(BaseModel):
    title: str | None = None
    map_link: str | None = None
    is_active: bool | None = None


class ManualCheckResponse(BaseModel):
    tracked_item_id: int
    checked_at: str
    status: str
    snapshot_id: int | None = None
    zone_count: int = 0
    added_count: int = 0
    removed_count: int = 0
    event_id: int | None = None
    error_message: str | None = None
    event_type: str | None = None
    tracked_item_title: str | None = None
    diff_image_path: str | None = None
