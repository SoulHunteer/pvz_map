import { NavLink, Outlet } from "react-router-dom";

import { useSession } from "../lib/session";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/tracked-items", label: "Trackings" },
  { to: "/tracked-items/new", label: "Create" },
  { to: "/tariff", label: "Tariff" }
];

export function Layout(): JSX.Element {
  const { me, auth, resetAuth, authError, loadingMe, refreshMe } = useSession();

  return (
    <div className="app-shell">
      <header className="topbar panel">
        <div>
          <p className="eyebrow">PVZ Monitor</p>
          <h1 className="title">Telegram-first MVP cabinet</h1>
        </div>

        <div className="topbar-meta">
          <div>
            <p className="meta-label">Telegram ID</p>
            <p className="meta-value">{auth.telegramId}</p>
          </div>
          <div>
            <p className="meta-label">Tariff</p>
            <p className="meta-value">{me?.tariff_plan || "-"}</p>
          </div>
          <button className="btn btn-ghost" type="button" onClick={() => void refreshMe()} disabled={loadingMe}>
            Refresh
          </button>
          <button className="btn btn-ghost" type="button" onClick={resetAuth}>
            Switch user
          </button>
        </div>
      </header>

      {authError && (
        <section className="panel error-banner">
          <p>{authError}</p>
        </section>
      )}

      <nav className="nav panel">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => (isActive ? "nav-link nav-link-active" : "nav-link")}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="page-grid">
        <Outlet />
      </main>
    </div>
  );
}
