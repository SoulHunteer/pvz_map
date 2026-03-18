from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SnapshotStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    EMPTY = "empty"


class ChangeEventType(str, Enum):
    CHANGED = "changed"
    NEW_ZONES = "new_zones"
    ZONES_REMOVED = "zones_removed"
    BECAME_EMPTY = "became_empty"
    RESTORED = "restored"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="user")
    tariff_plan: Mapped[str] = mapped_column(String(50), default="trial")
    tariff_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tracked_items: Mapped[list["TrackedItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class TrackedItem(Base):
    __tablename__ = "tracked_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    map_link: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(50), default="idle")
    last_zone_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="tracked_items")
    snapshots: Mapped[list["ZoneSnapshot"]] = relationship(
        back_populates="tracked_item", cascade="all, delete-orphan"
    )
    change_events: Mapped[list["ChangeEvent"]] = relationship(
        back_populates="tracked_item", cascade="all, delete-orphan"
    )


class ZoneSnapshot(Base):
    __tablename__ = "zone_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id", ondelete="CASCADE"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    status: Mapped[SnapshotStatus] = mapped_column(SqlEnum(SnapshotStatus), index=True)
    screenshot_path: Mapped[str] = mapped_column(Text)
    processed_image_path: Mapped[str] = mapped_column(Text)
    diff_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    zone_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    tracked_item: Mapped[TrackedItem] = relationship(back_populates="snapshots")
    detected_zones: Mapped[list["DetectedZone"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class DetectedZone(Base):
    __tablename__ = "detected_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("zone_snapshots.id", ondelete="CASCADE"), index=True)
    centroid_x: Mapped[float] = mapped_column(Float)
    centroid_y: Mapped[float] = mapped_column(Float)
    bbox_x: Mapped[int] = mapped_column(Integer)
    bbox_y: Mapped[int] = mapped_column(Integer)
    bbox_w: Mapped[int] = mapped_column(Integer)
    bbox_h: Mapped[int] = mapped_column(Integer)
    area: Mapped[float] = mapped_column(Float)
    perimeter: Mapped[float] = mapped_column(Float)
    polygon_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    contour_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    shape_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    snapshot: Mapped[ZoneSnapshot] = relationship(back_populates="detected_zones")


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id", ondelete="CASCADE"), index=True)
    previous_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("zone_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    current_snapshot_id: Mapped[int] = mapped_column(ForeignKey("zone_snapshots.id", ondelete="CASCADE"), index=True)
    added_count: Mapped[int] = mapped_column(Integer, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, default=0)
    event_type: Mapped[ChangeEventType] = mapped_column(SqlEnum(ChangeEventType), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tracked_item: Mapped[TrackedItem] = relationship(back_populates="change_events")
