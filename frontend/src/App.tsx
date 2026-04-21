import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthSetup } from "./components/AuthSetup";
import { Layout } from "./components/Layout";
import { useSession } from "./lib/session";
import { CreateTrackedItemPage } from "./pages/CreateTrackedItemPage";
import { DashboardPage } from "./pages/DashboardPage";
import { TariffPage } from "./pages/TariffPage";
import { TrackedItemDetailsPage } from "./pages/TrackedItemDetailsPage";
import { TrackedItemsPage } from "./pages/TrackedItemsPage";

const PENDING_REDIRECT_KEY = "pvz-pending-redirect";
const APP_BASENAME = "/app";

/**
 * Save the current URL (path + search) so we can restore it after login.
 * Only saves if there are meaningful query params (e.g. deep links from channel).
 */
function savePendingRedirect(): void {
  const url = window.location.pathname + window.location.search;
  // "Root" of cabinet is APP_BASENAME (or `${APP_BASENAME}/`) — don't save those.
  const pathname = window.location.pathname;
  const isRoot = pathname === APP_BASENAME || pathname === `${APP_BASENAME}/`;
  if (window.location.search && !isRoot) {
    localStorage.setItem(PENDING_REDIRECT_KEY, url);
  }
}

function consumePendingRedirect(): string | null {
  const url = localStorage.getItem(PENDING_REDIRECT_KEY);
  if (url) {
    localStorage.removeItem(PENDING_REDIRECT_KEY);
  }
  return url;
}

function AppRoutes(): JSX.Element {
  const { auth } = useSession();

  if (!auth.telegramId.trim()) {
    // Save deep-link URL before showing auth screen
    savePendingRedirect();
    return <AuthSetup />;
  }

  // After login, check if we need to redirect to a saved deep-link URL
  const pending = consumePendingRedirect();
  if (pending && pending !== window.location.pathname + window.location.search) {
    // Replace the current URL so BrowserRouter picks it up
    window.history.replaceState({}, "", pending);
  }

  return (
    <BrowserRouter basename={APP_BASENAME}>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="tracked-items" element={<TrackedItemsPage />} />
          <Route path="tracked-items/new" element={<CreateTrackedItemPage />} />
          <Route path="tracked-items/:id" element={<TrackedItemDetailsPage />} />
          <Route path="tariff" element={<TariffPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default AppRoutes;
