import { Link } from "react-router-dom";

import { toPercent } from "../lib/format";
import { useSession } from "../lib/session";

const plans = [
  { key: "trial", title: "Trial / Free", limit: 1 },
  { key: "base", title: "Base", limit: 5 },
  { key: "pro", title: "Pro", limit: 20 }
];

export function TariffPage(): JSX.Element {
  const { me } = useSession();

  if (!me) {
    return <section className="panel">Loading tariff...</section>;
  }

  const usagePercent = toPercent(me.tracked_items_total, me.tracked_items_limit);

  return (
    <section className="panel section-stack">
      <div className="section-head">
        <h2>Tariff and limits</h2>
        <Link className="btn btn-ghost" to="/tracked-items/new">
          Add tracking
        </Link>
      </div>

      <div className="tariff-card">
        <p className="meta-label">Current plan</p>
        <p className="metric">{me.tariff_plan}</p>
        <p className="muted">Active: {me.is_active ? "yes" : "no"}</p>
        <p className="muted">Tariff end: {me.tariff_end_at ? new Date(me.tariff_end_at).toLocaleString("ru-RU") : "not limited"}</p>
        <p className="muted">
          Usage: {me.tracked_items_total} / {me.tracked_items_limit}
        </p>
        <div className="progress">
          <span style={{ width: `${usagePercent}%` }} />
        </div>
      </div>

      <div className="card-grid">
        {plans.map((plan) => (
          <article key={plan.key} className={plan.key === me.tariff_plan ? "card card-highlight" : "card"}>
            <h3>{plan.title}</h3>
            <p className="muted">Tracked items limit: {plan.limit}</p>
          </article>
        ))}
      </div>

      <p className="muted">
        Payment integration is not included in MVP yet. Tariff values are managed in backend business logic and can be
        connected to billing later.
      </p>
    </section>
  );
}
