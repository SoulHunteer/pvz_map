import {
  ChangeEvent,
  CreateTrackedItemRequest,
  CreateTrackedItemResponse,
  DevAuth,
  ManualCheckResult,
  Snapshot,
  SnapshotZoneDiff,
  TrackedItem,
  TrackedItemDetails,
  UpdateTrackedItemRequest,
  UserSummary
} from "./types";

const rawApiBase = import.meta.env.VITE_API_BASE_URL;
const apiBase = (rawApiBase !== undefined ? rawApiBase : "http://localhost:8000").replace(/\/+$/, "");
const rawAssetBase = import.meta.env.VITE_ASSET_BASE_URL;
const assetBase = (rawAssetBase !== undefined ? rawAssetBase : apiBase).replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function buildHeaders(auth: DevAuth): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Dev-Telegram-Id": auth.telegramId.trim()
  };

  if (auth.username?.trim()) {
    headers["X-Dev-Username"] = auth.username.trim();
  }
  if (auth.fullName?.trim()) {
    headers["X-Dev-Full-Name"] = auth.fullName.trim();
  }

  return headers;
}

async function request<T>(path: string, auth: DevAuth, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      ...buildHeaders(auth),
      ...(init?.headers || {})
    }
  });

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        message = payload.detail;
      }
    } catch {
      // Ignore non-JSON responses
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function resolveArtifactUrl(path?: string | null): string | null {
  if (!path) {
    return null;
  }

  const normalized = path.replace(/\\/g, "/");
  const filename = normalized.split("/").pop();
  if (!filename) {
    return null;
  }

  if (normalized.includes("/screenshots/")) {
    return `${assetBase}/artifacts/screenshots/${filename}`;
  }
  if (normalized.includes("/processed/")) {
    return `${assetBase}/artifacts/processed/${filename}`;
  }
  if (normalized.includes("/diffs/")) {
    return `${assetBase}/artifacts/diffs/${filename}`;
  }
  return null;
}

export const api = {
  getMe(auth: DevAuth): Promise<UserSummary> {
    return request<UserSummary>("/api/me", auth);
  },

  listTrackedItems(auth: DevAuth): Promise<TrackedItem[]> {
    return request<TrackedItem[]>("/api/tracked-items", auth);
  },

  createTrackedItem(auth: DevAuth, payload: CreateTrackedItemRequest): Promise<CreateTrackedItemResponse> {
    return request<CreateTrackedItemResponse>("/api/tracked-items", auth, {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },

  getTrackedItem(auth: DevAuth, trackedItemId: number): Promise<TrackedItemDetails> {
    return request<TrackedItemDetails>(`/api/tracked-items/${trackedItemId}`, auth);
  },

  runManualCheck(auth: DevAuth, trackedItemId: number): Promise<ManualCheckResult> {
    return request<ManualCheckResult>(`/api/tracked-items/${trackedItemId}/check`, auth, {
      method: "POST"
    });
  },

  patchTrackedItem(auth: DevAuth, trackedItemId: number, payload: UpdateTrackedItemRequest): Promise<TrackedItem> {
    return request<TrackedItem>(`/api/tracked-items/${trackedItemId}`, auth, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
  },

  deleteTrackedItem(auth: DevAuth, trackedItemId: number): Promise<{ deleted: boolean; tracked_item_id: number }> {
    return request<{ deleted: boolean; tracked_item_id: number }>(`/api/tracked-items/${trackedItemId}`, auth, {
      method: "DELETE"
    });
  },

  listSnapshots(auth: DevAuth, trackedItemId: number, limit = 10): Promise<Snapshot[]> {
    return request<Snapshot[]>(`/api/tracked-items/${trackedItemId}/snapshots?limit=${limit}`, auth);
  },

  listEvents(auth: DevAuth, trackedItemId: number, limit = 10): Promise<ChangeEvent[]> {
    return request<ChangeEvent[]>(`/api/tracked-items/${trackedItemId}/events?limit=${limit}`, auth);
  },

  getSnapshotZoneDiff(
    auth: DevAuth,
    trackedItemId: number,
    snapshotId: number,
    previousSnapshotId?: number | null
  ): Promise<SnapshotZoneDiff> {
    const query =
      previousSnapshotId === undefined || previousSnapshotId === null
        ? ""
        : `?previous_snapshot_id=${previousSnapshotId}`;
    return request<SnapshotZoneDiff>(
      `/api/tracked-items/${trackedItemId}/snapshots/${snapshotId}/zone-diff${query}`,
      auth
    );
  }
};