export type SnapshotStatus = "success" | "error" | "empty";

export interface UserSummary {
  id: number;
  telegram_user_id: number;
  username: string | null;
  full_name: string | null;
  role: string;
  tariff_plan: string;
  tariff_end_at: string | null;
  is_active: boolean;
  tracked_items_total: number;
  tracked_items_active: number;
  tracked_items_limit: number;
}

export interface TrackedItem {
  id: number;
  user_id: number;
  title: string;
  map_link: string;
  is_active: boolean;
  last_check_at: string | null;
  last_success_at: string | null;
  last_status: string;
  last_zone_count: number;
  created_at: string;
  updated_at: string;
}

export interface Snapshot {
  id: number;
  tracked_item_id: number;
  checked_at: string;
  status: SnapshotStatus;
  screenshot_path: string;
  processed_image_path: string;
  diff_image_path: string | null;
  zone_count: number;
  error_message: string | null;
}

export interface ChangeEvent {
  id: number;
  tracked_item_id: number;
  tracked_item_title: string;
  previous_snapshot_id: number | null;
  current_snapshot_id: number;
  added_count: number;
  removed_count: number;
  event_type: string;
  created_at: string;
  notification_sent_at: string | null;
}

export interface ManualCheckResult {
  tracked_item_id: number;
  checked_at: string;
  status: string;
  snapshot_id: number | null;
  zone_count: number;
  added_count: number;
  removed_count: number;
  event_id: number | null;
  error_message: string | null;
  event_type: string | null;
  tracked_item_title: string | null;
  diff_image_path: string | null;
}

export interface TrackedItemDetails {
  item: TrackedItem;
  snapshots: Snapshot[];
  events: ChangeEvent[];
}

export interface CreateTrackedItemRequest {
  title?: string;
  map_link: string;
  is_active?: boolean;
  run_initial_check?: boolean;
}

export interface CreateTrackedItemResponse {
  item: TrackedItem;
  initial_check: ManualCheckResult | null;
}

export interface UpdateTrackedItemRequest {
  title?: string;
  map_link?: string;
  is_active?: boolean;
}

export interface SnapshotZoneOverlay {
  status: "added" | "removed" | "stable";
  label: string;
  centroid_x: number;
  centroid_y: number;
  bbox_x: number;
  bbox_y: number;
  bbox_w: number;
  bbox_h: number;
  area: number;
  perimeter: number;
  polygon: number[][];
  contour: number[][];
  shape_hash: string | null;
  appeared_at: string | null;
  updated_at: string | null;
  last_seen_at: string | null;
}

export interface SnapshotZoneDiff {
  tracked_item_id: number;
  snapshot_id: number;
  snapshot_checked_at: string;
  previous_snapshot_id: number | null;
  counts: {
    added: number;
    removed: number;
    stable: number;
    total_current: number;
  };
  zones: SnapshotZoneOverlay[];
}

export interface DevAuth {
  telegramId: string;
  username?: string;
  fullName?: string;
}



