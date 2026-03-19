import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthSetup } from "./components/AuthSetup";
import { Layout } from "./components/Layout";
import { useSession } from "./lib/session";
import { CreateTrackedItemPage } from "./pages/CreateTrackedItemPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LastCheckPhotoPage } from "./pages/LastCheckPhotoPage";
import { TariffPage } from "./pages/TariffPage";
import { TrackedItemDetailsPage } from "./pages/TrackedItemDetailsPage";
import { TrackedItemsPage } from "./pages/TrackedItemsPage";

function AppRoutes(): JSX.Element {
  const { auth } = useSession();

  if (!auth.telegramId.trim()) {
    return <AuthSetup />;
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="tracked-items" element={<TrackedItemsPage />} />
          <Route path="tracked-items/new" element={<CreateTrackedItemPage />} />
          <Route path="tracked-items/:id" element={<TrackedItemDetailsPage />} />
          <Route path="tracked-items/:id/photo" element={<LastCheckPhotoPage />} />
          <Route path="tariff" element={<TariffPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default AppRoutes;
