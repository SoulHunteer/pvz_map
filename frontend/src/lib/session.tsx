import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api } from "./api";
import { clearAuth, loadAuth, saveAuth } from "./auth";
import { DevAuth, UserSummary } from "./types";

interface SessionContextValue {
  auth: DevAuth;
  me: UserSummary | null;
  loadingMe: boolean;
  authError: string | null;
  setAuth: (auth: DevAuth) => Promise<void>;
  resetAuth: () => void;
  refreshMe: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

export function SessionProvider({ children }: { children: ReactNode }): JSX.Element {
  const [auth, setAuthState] = useState<DevAuth>(() => loadAuth());
  const [me, setMe] = useState<UserSummary | null>(null);
  const [loadingMe, setLoadingMe] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const refreshMe = useCallback(async () => {
    if (!auth.telegramId.trim()) {
      setMe(null);
      setAuthError(null);
      return;
    }

    setLoadingMe(true);
    try {
      const summary = await api.getMe(auth);
      setMe(summary);
      setAuthError(null);
      saveAuth(auth);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load profile";
      setAuthError(message);
      setMe(null);
    } finally {
      setLoadingMe(false);
    }
  }, [auth]);

  useEffect(() => {
    void refreshMe();
  }, [refreshMe]);

  const setAuth = useCallback(async (next: DevAuth) => {
    setAuthState(next);
  }, []);

  const resetAuth = useCallback(() => {
    clearAuth();
    setAuthState({ telegramId: "" });
    setMe(null);
    setAuthError(null);
  }, []);

  const value = useMemo<SessionContextValue>(
    () => ({
      auth,
      me,
      loadingMe,
      authError,
      setAuth,
      resetAuth,
      refreshMe
    }),
    [auth, me, loadingMe, authError, setAuth, resetAuth, refreshMe]
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return value;
}
