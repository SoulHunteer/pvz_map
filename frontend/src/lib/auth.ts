import { DevAuth } from "./types";

const STORAGE_KEY = "pvz-monitor-dev-auth";

export function loadAuth(): DevAuth {
  if (typeof window === "undefined") {
    return { telegramId: "" };
  }

  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return { telegramId: "" };
  }

  try {
    const parsed = JSON.parse(raw) as DevAuth;
    return {
      telegramId: parsed.telegramId || "",
      username: parsed.username || "",
      fullName: parsed.fullName || ""
    };
  } catch {
    return { telegramId: "" };
  }
}

export function saveAuth(auth: DevAuth): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
}

export function clearAuth(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(STORAGE_KEY);
}
