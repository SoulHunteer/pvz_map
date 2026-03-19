import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import { api } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useSession } from "../lib/session";
import { ChangeEvent, TrackedItem } from "../lib/types";

export function DashboardPage(): JSX.Element {
  const { auth } = useSession();
  const [items, setItems] = useState<TrackedItem[]>([]);
  const [events, setEvents] = useState<ChangeEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const trackedItems = await api.listTrackedItems(auth);
        if (cancelled) {
          return;
        }
        setItems(trackedItems);

        const eventRows = await Promise.all(
          trackedItems.map(async (item) => {
            try {
              return await api.listEvents(auth, item.id, 4);
            } catch {
              return [] as ChangeEvent[];
            }
          })
        );

        if (cancelled) {
          return;
        }

        const merged = eventRows
          .flat()
          .sort((a, b) => {
            const left = new Date(a.created_at).getTime();
            const right = new Date(b.created_at).getTime();
            return right - left;
          })
          .slice(0, 10);
        setEvents(merged);
      } catch (loadError) {
        if (!cancelled) {
          const message = loadError instanceof Error ? loadError.message : "Failed to load dashboard";
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [auth]);

  const stats = useMemo(() => {
    const active = items.filter((item) => item.is_active).length;
    const lastSuccess = items
      .map((item) => item.last_success_at)
      .filter((value): value is string => Boolean(value))
      .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0];

    return {
      total: items.length,
      active,
      recentEvents: events.length,
      lastSuccess
    };
  }, [items, events]);

  if (loading) {
    return <section className="panel">Loading dashboard...</section>;
  }

  if (error) {
    return <section className="panel error-text">{error}</section>;
  }

  return (
    <>
      <section className="panel stats-grid">
        <article>
          <p className="meta-label">Active trackings</p>
          <p className="metric">{stats.active}</p>
        </article>
        <article>
          <p className="meta-label">All trackings</p>
          <p className="metric">{stats.total}</p>
        </article>
        <article>
          <p className="meta-label">Recent events</p>
          <p className="metric">{stats.recentEvents}</p>
        </article>
        <article>
          <p className="meta-label">Last success check</p>
          <p className="metric metric-small">{formatDateTime(stats.lastSuccess)}</p>
        </article>
      </section>

      <section className="panel section-stack">
        <div className="section-head">
          <h2>Tracked items</h2>
          <Link className="btn btn-primary" to="/tracked-items/new">
            Add tracking
          </Link>
        </div>

        {items.length === 0 ? (
          <EmptyState
            title="No trackings yet"
            description="Create the first tracking to start receiving Telegram notifications."
          />
        ) : (
          <div className="card-grid">
            {items.map((item) => (
              <article key={item.id} className="card">
                <div className="card-head">
                  <h3>{item.title}</h3>
                  <StatusBadge status={item.last_status} />
                </div>
                <p className="muted">Zones: {item.last_zone_count}</p>
                <p className="muted">Last check: {formatDateTime(item.last_check_at)}</p>
                <p className="muted">Monitoring: {item.is_active ? "active" : "paused"}</p>
                <div className="actions-row">
                  <Link className="btn btn-ghost" to={`/tracked-items/${item.id}/photo`}>
                    Просмотреть фото проверки
                  </Link>
                  <Link className="btn btn-ghost" to={`/tracked-items/${item.id}`}>Редактировать</Link>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="panel section-stack">
        <h2>Latest changes</h2>
        {events.length === 0 ? (
          <p className="muted">No change events yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Item</th>
                  <th>Type</th>
                  <th>Added</th>
                  <th>Removed</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td>{formatDateTime(event.created_at)}</td>
                    <td>{event.tracked_item_title}</td>
                    <td>{event.event_type}</td>
                    <td>{event.added_count}</td>
                    <td>{event.removed_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}


