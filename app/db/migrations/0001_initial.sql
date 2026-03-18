-- Initial schema for MVP backend core.
-- Managed via SQLAlchemy create_all in app/db/init_db.py.

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  telegram_user_id INTEGER NOT NULL UNIQUE,
  username VARCHAR(255),
  full_name VARCHAR(255),
  role VARCHAR(50) NOT NULL DEFAULT 'user',
  tariff_plan VARCHAR(50) NOT NULL DEFAULT 'trial',
  tariff_end_at DATETIME,
  is_active BOOLEAN NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS tracked_items (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  title VARCHAR(255) NOT NULL,
  map_link TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT 1,
  last_check_at DATETIME,
  last_success_at DATETIME,
  last_status VARCHAR(50) NOT NULL DEFAULT 'idle',
  last_zone_count INTEGER NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS zone_snapshots (
  id INTEGER PRIMARY KEY,
  tracked_item_id INTEGER NOT NULL,
  checked_at DATETIME NOT NULL,
  status VARCHAR(20) NOT NULL,
  screenshot_path TEXT NOT NULL,
  processed_image_path TEXT NOT NULL,
  diff_image_path TEXT,
  zone_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  FOREIGN KEY (tracked_item_id) REFERENCES tracked_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS detected_zones (
  id INTEGER PRIMARY KEY,
  snapshot_id INTEGER NOT NULL,
  centroid_x FLOAT NOT NULL,
  centroid_y FLOAT NOT NULL,
  bbox_x INTEGER NOT NULL,
  bbox_y INTEGER NOT NULL,
  bbox_w INTEGER NOT NULL,
  bbox_h INTEGER NOT NULL,
  area FLOAT NOT NULL,
  perimeter FLOAT NOT NULL,
  polygon_json TEXT,
  contour_json TEXT,
  shape_hash VARCHAR(128),
  FOREIGN KEY (snapshot_id) REFERENCES zone_snapshots(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS change_events (
  id INTEGER PRIMARY KEY,
  tracked_item_id INTEGER NOT NULL,
  previous_snapshot_id INTEGER,
  current_snapshot_id INTEGER NOT NULL,
  added_count INTEGER NOT NULL DEFAULT 0,
  removed_count INTEGER NOT NULL DEFAULT 0,
  event_type VARCHAR(30) NOT NULL,
  created_at DATETIME NOT NULL,
  notification_sent_at DATETIME,
  FOREIGN KEY (tracked_item_id) REFERENCES tracked_items(id) ON DELETE CASCADE,
  FOREIGN KEY (previous_snapshot_id) REFERENCES zone_snapshots(id) ON DELETE SET NULL,
  FOREIGN KEY (current_snapshot_id) REFERENCES zone_snapshots(id) ON DELETE CASCADE
);
